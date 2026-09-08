"""Carrega o resultado da analise da LLM (Excel) para o SQLite.

A tela le do banco, nao de planilha. Este script fecha o ciclo:
    12_sob_demanda_testar_llm_opiniao.py  ->  Excel
    13_sob_demanda_carregar_opiniao_ia.py ->  SQLite

Duas coisas acontecem aqui:

1. Cada linha vira um registro em `opiniao_ia`, chaveado por fonte_opiniao_id.
   A chave do Excel e (cnpj, ano_referencia, origem), que e exatamente a UNIQUE
   de fontes_opiniao_auditor - o join resolve o id.

2. `fundos.classificacao_risco` e recalculado a partir da DF mais recente de cada
   fundo. Isso substitui a heuristica de 04_semanal_update_classificacao_risco.py
   onde ha analise da LLM: a heuristica ve so o rotulo da opiniao e por isso perde
   enfase, continuidade operacional e encerramento; a LLM le o texto. Onde nao ha
   analise, o valor da heuristica permanece.

Uso:
    python pipeline/13_sob_demanda_carregar_opiniao_ia.py
    python pipeline/13_sob_demanda_carregar_opiniao_ia.py --entrada exports/outro.xlsx
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path
from typing import List, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from pipeline.utils import obter_conexao, registrar_log

NOME_PIPELINE = "carregar_opiniao_ia"
NOME_BASE_COMPETENCIA = "opiniao_ia"

ENTRADA_PADRAO = config.BASE_DIR / "exports" / "opiniao_2026_llm_resultado.xlsx"

# Ordem de gravidade - usada para escolher a pior analise quando o fundo tem mais
# de uma fonte no mesmo ano (DF e PARECER AUD. do mesmo exercicio, por exemplo).
SEVERIDADE = {"BAIXO": 1, "MEDIO": 2, "ALTO": 3}

DDL = """
CREATE TABLE IF NOT EXISTS opiniao_ia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte_opiniao_id INTEGER NOT NULL UNIQUE REFERENCES fontes_opiniao_auditor (id),
    fundo_cnpj TEXT NOT NULL,
    ano_referencia INTEGER NOT NULL,
    manifestacao TEXT,
    classificacao_risco TEXT,
    justificativa TEXT,
    impacto TEXT,
    divergencia_regex INTEGER NOT NULL DEFAULT 0,
    celula_invalida INTEGER NOT NULL DEFAULT 0,
    status_analista TEXT NOT NULL DEFAULT 'PENDENTE',
    modelo TEXT,
    erro TEXT,
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    atualizado_em TEXT DEFAULT (datetime('now', 'localtime'))
)
"""

INDICES = [
    "CREATE INDEX IF NOT EXISTS ix_opiniao_ia_fundo ON opiniao_ia (fundo_cnpj, ano_referencia)",
    "CREATE INDEX IF NOT EXISTS ix_opiniao_ia_risco ON opiniao_ia (classificacao_risco)",
    "CREATE INDEX IF NOT EXISTS ix_opiniao_ia_status ON opiniao_ia (status_analista)",
]

# Celulas que a matriz do prompt permite. Serve de checagem determinstica: o
# modelo pode desobedecer a propria tabela, e quando desobedece a linha vai para
# revisao humana em vez de entrar silenciosamente na base.
CELULAS_VALIDAS = {
    "SEM_RESSALVA": {"BAIXO"},
    "ENCERRAMENTO": {"BAIXO"},
    "ENFASE_OUTROS": {"BAIXO", "MEDIO", "ALTO"},
    "CONTINUIDADE": {"MEDIO", "ALTO"},
    "RESSALVA": {"MEDIO", "ALTO"},
    "ADVERSA": {"ALTO"},
    "ABSTENCAO": {"ALTO"},
}

# Como o tipo detectado por regex se traduz no vocabulario da LLM.
EQUIVALENCIA_TIPO = {
    "SEM_RESSALVA": {"SEM_RESSALVA", "ENCERRAMENTO", "ENFASE_OUTROS", "CONTINUIDADE"},
    "COM_RESSALVA": {"RESSALVA"},
    "ABSTENCAO": {"ABSTENCAO"},
    "ADVERSA": {"ADVERSA"},
}


def _texto(valor) -> str | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip()
    return texto or None


def montar_registros(df: pd.DataFrame, ids: dict) -> Tuple[List[tuple], int]:
    """Converte o Excel em tuplas prontas para o INSERT. Retorna (linhas, sem_id)."""
    linhas: List[tuple] = []
    sem_id = 0

    for r in df.itertuples(index=False):
        chave = (str(r.cnpj).zfill(14), int(r.ano_referencia), str(r.origem))
        fonte_id = ids.get(chave)
        if fonte_id is None:
            sem_id += 1
            continue

        manifestacao = _texto(r.ia_manifestacao)
        classificacao = _texto(r.ia_classificacao)
        tipo_regex = _texto(r.tipo_opiniao_detectado)

        divergiu = bool(
            manifestacao and tipo_regex
            and manifestacao not in EQUIVALENCIA_TIPO.get(tipo_regex, set())
        )
        invalida = bool(
            manifestacao and classificacao not in (None, "INDETERMINADO")
            and classificacao not in CELULAS_VALIDAS.get(manifestacao, set())
        )

        linhas.append((
            fonte_id, chave[0], chave[1], manifestacao, classificacao,
            _texto(r.ia_justificativa), _texto(r.ia_impacto),
            int(divergiu), int(invalida), "gpt-5-mini", _texto(r.ia_erro),
        ))

    return linhas, sem_id


def gravar(conn, linhas: List[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO opiniao_ia (
            fonte_opiniao_id, fundo_cnpj, ano_referencia, manifestacao,
            classificacao_risco, justificativa, impacto,
            divergencia_regex, celula_invalida, modelo, erro
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (fonte_opiniao_id) DO UPDATE SET
            manifestacao = excluded.manifestacao,
            classificacao_risco = excluded.classificacao_risco,
            justificativa = excluded.justificativa,
            impacto = excluded.impacto,
            divergencia_regex = excluded.divergencia_regex,
            celula_invalida = excluded.celula_invalida,
            modelo = excluded.modelo,
            erro = excluded.erro,
            atualizado_em = datetime('now', 'localtime')
        """,
        linhas,
    )
    conn.commit()


def propagar_para_fundos(conn) -> int:
    """Atualiza fundos.classificacao_risco com a analise da DF mais recente.

    Criterio: por fundo, pega o maior ano_referencia analisado; havendo mais de
    uma fonte nesse ano, prevalece a de maior severidade. Fundo sem analise nao e
    tocado - continua com o que a heuristica do pipeline 04 deixou.
    """
    df = pd.read_sql_query(
        """
        SELECT fundo_cnpj, ano_referencia, classificacao_risco, justificativa
        FROM opiniao_ia
        WHERE classificacao_risco IN ('BAIXO', 'MEDIO', 'ALTO')
        """,
        conn,
    )
    if df.empty:
        return 0

    df["_sev"] = df["classificacao_risco"].map(SEVERIDADE)
    escolhidas = (
        df.sort_values(["ano_referencia", "_sev"])
          .groupby("fundo_cnpj", as_index=False)
          .tail(1)
    )

    conn.executemany(
        """
        UPDATE fundos
           SET classificacao_risco = ?,
               motivo_classificacao_risco = ?,
               atualizado_em = datetime('now', 'localtime')
         WHERE cnpj = ?
        """,
        [
            (linha.classificacao_risco, f"{linha.justificativa} (DF {linha.ano_referencia})",
             linha.fundo_cnpj)
            for linha in escolhidas.itertuples(index=False)
        ],
    )
    conn.commit()
    return len(escolhidas)


def carregar(entrada: Path) -> None:
    inicio = time.monotonic()
    competencia = date.today().strftime("%Y%m")
    conn = obter_conexao()

    try:
        conn.execute(DDL)
        for indice in INDICES:
            conn.execute(indice)
        conn.commit()

        df = pd.read_excel(entrada)
        print(f"{len(df):,} linhas em {entrada.name}")

        ids = {
            (c, a, o): i
            for i, c, a, o in conn.execute(
                "SELECT id, fundo_cnpj, ano_referencia, origem FROM fontes_opiniao_auditor"
            )
        }
        linhas, sem_id = montar_registros(df, ids)
        gravar(conn, linhas)
        print(f"  gravadas em opiniao_ia ....... {len(linhas):,}")
        if sem_id:
            print(f"  sem fonte correspondente ..... {sem_id:,} (ignoradas)")

        divergencias = sum(l[7] for l in linhas)
        invalidas = sum(l[8] for l in linhas)
        print(f"  divergem do regex ............ {divergencias:,}")
        print(f"  celula fora da matriz ........ {invalidas:,}")
        print(f"  -> para revisao humana ....... {sum(1 for l in linhas if l[7] or l[8]):,}")

        atualizados = propagar_para_fundos(conn)
        print(f"\n  fundos com risco atualizado .. {atualizados:,}")
        print(pd.read_sql_query(
            "SELECT classificacao_risco, COUNT(*) AS fundos FROM fundos "
            "WHERE classificacao_risco IS NOT NULL GROUP BY 1 ORDER BY 2 DESC", conn
        ).to_string(index=False))

        registrar_log(
            conn, NOME_PIPELINE, NOME_BASE_COMPETENCIA, "SUCESSO", competencia=competencia,
            linhas_lidas=len(df), linhas_processadas=len(linhas),
            linhas_inseridas=len(linhas), linhas_atualizadas=atualizados,
            linhas_ignoradas=sem_id, duracao_segundos=time.monotonic() - inicio,
        )
    except Exception as exc:
        registrar_log(
            conn, NOME_PIPELINE, NOME_BASE_COMPETENCIA, "ERRO", competencia=competencia,
            mensagem_erro=str(exc), duracao_segundos=time.monotonic() - inicio,
        )
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", type=Path, default=ENTRADA_PADRAO)
    args = parser.parse_args()
    carregar(args.entrada)
