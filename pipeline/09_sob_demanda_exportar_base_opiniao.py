"""Exporta para Excel tudo que ja foi extraido em fontes_opiniao_extracao.

Substitui o caminho antigo (exportar uma vez e depois reprocessar aquele Excel com
08_sob_demanda_recortar_secoes_excel.py), que congelava o universo no snapshot do
dia da exportacao - foi assim que o export de 19.419 linhas ficou preso as extracoes
existentes em 16/08 e nao enxergou as origens carregadas depois (MANUAL_*, DFIN_FII,
o grosso de EVENTUAL_DF e EVENTUAL_PARECER_AUD).

Aqui o universo e sempre o estado ATUAL do banco: 1 linha por extracao salva. O
recorte das secoes e recalculado na hora a partir do PDF em cache (as colunas de
recorte em fontes_opiniao_extracao ainda estao vazias na base de producao), com
fallback para a janela antiga quando o PDF nao esta mais no disco.

O join com `fundos` e LEFT de proposito: fundo cancelado/liquidado (e, quando o
escopo de extracao roda sem filtro, tambem Bradesco/BEM) publica DF e precisa
aparecer. Quando o CNPJ nao esta no cadastro ativo, os campos cadastrais vem vazios
e a coluna fundo_no_cadastro marca "Nao" - e fundo fora do cadastro, nao falha de
extracao.

Como o gargalo e o parsing do PDF (CPU, nao rede), roda em pool de PROCESSOS.

Uso:
    python pipeline/09_sob_demanda_exportar_base_opiniao.py
    python pipeline/09_sob_demanda_exportar_base_opiniao.py --saida exports/base.xlsx
    python pipeline/09_sob_demanda_exportar_base_opiniao.py --workers 8
    python pipeline/09_sob_demanda_exportar_base_opiniao.py --sem-pdf   # so a janela antiga (rapido, sem enfase)
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from pipeline.opiniao_secoes import (
    classificar_triagem,
    extrair_secoes,
    recortar_do_pdf,
    remontar_janela,
)
from pipeline.utils import ORDEM_PRIORIDADE_ORIGEM, obter_conexao

COLUNAS_SECOES = [
    "trecho_opiniao_secao",
    "trecho_base_opiniao",
    "trecho_enfase_outros",
    "secoes_adicionais",
    "titulo_opiniao",
    "titulo_base",
    "tipo_opiniao_detectado",
    "metodo_recorte",
]
COLUNAS_TRIAGEM = ["precisa_llm", "motivo_llm"]
WORKERS_PADRAO = max(1, (os.cpu_count() or 4) - 1)

def _sql_prioridade_origem() -> str:
    """Mesmo criterio de desempate do 06 - a origem mais direta primeiro."""
    casos = " ".join(f"WHEN '{origem}' THEN {p}" for origem, p in ORDEM_PRIORIDADE_ORIGEM.items())
    return f"CASE f.origem {casos} ELSE 99 END"


# Duas familias de linha entram no export:
#   1. toda extracao de PDF salva em fontes_opiniao_extracao;
#   2. fundo que NAO tem nenhuma extracao mas ja tem opiniao classificada pela
#      propria CVM (DFIN_FII / ARQUIVO_MANUAL_OPINIAO_PRONTA) - nunca vai ter PDF
#      extraido, porque o 06 pula quem ja tem opiniao_estruturada. Sem esse ramo
#      esses fundos sumiam do Excel apesar de a resposta ja estar no banco.
CONSULTA = f"""
    WITH nomes AS (
        SELECT fundo_cnpj, MAX(nome_fundo) AS nome
        FROM fontes_opiniao_auditor
        WHERE nome_fundo IS NOT NULL
        GROUP BY fundo_cnpj
    ),
    sem_extracao AS (
        SELECT f.id,
               ROW_NUMBER() OVER (
                   PARTITION BY f.fundo_cnpj
                   ORDER BY f.ano_referencia DESC, {_sql_prioridade_origem()}
               ) AS posicao
        FROM fontes_opiniao_auditor f
        WHERE f.opiniao_estruturada IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM fontes_opiniao_extracao e
            JOIN fontes_opiniao_auditor f2 ON f2.id = e.fonte_opiniao_id
            WHERE f2.fundo_cnpj = f.fundo_cnpj
        )
    ),
    selecionadas AS (
        SELECT e.id AS extracao_id, e.fonte_opiniao_id AS fonte_id
        FROM fontes_opiniao_extracao e
        UNION ALL
        SELECT NULL AS extracao_id, id AS fonte_id
        FROM sem_extracao WHERE posicao = 1
    )
    SELECT
        f.fundo_cnpj                                            AS cnpj,
        COALESCE(fu.denominacao_social, f.nome_fundo, n.nome)   AS nome_fundo,
        CASE WHEN fu.cnpj IS NULL THEN 'Nao' ELSE 'Sim' END     AS fundo_no_cadastro,
        fu.situacao,
        fu.classe,
        fu.administrador_nome                                   AS administrador,
        fu.gestor_nome                                          AS gestor,
        fu.auditor_nome                                         AS auditor,
        f.ano_referencia,
        f.origem,
        f.opiniao_estruturada                                   AS opiniao_cvm,
        e.trecho_opiniao_secao,
        e.trecho_base_opiniao,
        f.link_arquivo,
        e.numero_paginas,
        e.tamanho_pdf_bytes,
        e.encontrou_secao_opiniao,
        e.metodo_extracao,
        e.mensagem_erro,
        e.caminho_pdf,
        e.atualizado_em
    FROM selecionadas s
    JOIN fontes_opiniao_auditor f ON f.id = s.fonte_id
    LEFT JOIN fontes_opiniao_extracao e ON e.id = s.extracao_id
    LEFT JOIN fundos fu ON fu.cnpj = f.fundo_cnpj
    LEFT JOIN nomes n ON n.fundo_cnpj = f.fundo_cnpj
    ORDER BY f.fundo_cnpj, f.ano_referencia DESC
"""


def carregar(conn) -> pd.DataFrame:
    return pd.read_sql_query(CONSULTA, conn)


def recortar(df: pd.DataFrame, usar_pdf: bool, workers: int) -> list:
    """Recorte por linha: PDF do cache quando disponivel, senao a janela antiga."""
    secoes = [
        extrair_secoes(remontar_janela(linha.trecho_opiniao_secao, linha.trecho_base_opiniao))
        for linha in df.itertuples(index=False)
    ]
    if not usar_pdf:
        return secoes

    caminhos = df["caminho_pdf"].tolist()
    print(f"Lendo {len(caminhos)} PDFs do cache em {workers} processos "
          f"(necessario para achar Enfase/Outros assuntos)...")
    inicio = time.monotonic()
    substituidos = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for posicao, resultado in enumerate(executor.map(recortar_do_pdf, caminhos, chunksize=16)):
            if resultado is not None:
                secoes[posicao] = resultado
                substituidos += 1
            if (posicao + 1) % 500 == 0:
                decorrido = time.monotonic() - inicio
                restante = decorrido / (posicao + 1) * (len(caminhos) - posicao - 1)
                print(f"  [{posicao + 1}/{len(caminhos)}] {decorrido / 60:.1f} min decorridos, "
                      f"~{restante / 60:.1f} min restantes", flush=True)
    print(f"  recortados a partir do PDF: {substituidos}/{len(caminhos)} "
          f"em {(time.monotonic() - inicio) / 60:.1f} min")
    return secoes


def montar_saida(df: pd.DataFrame, secoes: list) -> pd.DataFrame:
    saida = df.copy()
    novos = pd.DataFrame(secoes, index=saida.index)
    for coluna in COLUNAS_SECOES:
        saida[coluna] = novos[coluna]

    triagem = [classificar_triagem(s) for s in secoes]
    saida["precisa_llm"] = [t[0] for t in triagem]
    saida["motivo_llm"] = [t[1] for t in triagem]

    # Deixa o que a LLM vai consumir logo apos a identificacao do fundo.
    prioritarias = COLUNAS_TRIAGEM + COLUNAS_SECOES
    restantes = [c for c in saida.columns if c not in prioritarias]
    corte = restantes.index("opiniao_cvm") + 1 if "opiniao_cvm" in restantes else len(restantes)
    return saida[restantes[:corte] + prioritarias + restantes[corte:]]


def imprimir_resumo(saida: pd.DataFrame) -> None:
    print(f"\n--- cobertura ---")
    print(f"  linhas: {len(saida)}")
    print(f"  fundos distintos: {saida['cnpj'].nunique()}")
    print(saida["fundo_no_cadastro"].value_counts().to_string())
    print("\n--- origem ---")
    print(saida["origem"].value_counts().to_string())
    print("\n--- tipo_opiniao_detectado ---")
    print(saida["tipo_opiniao_detectado"].value_counts(dropna=False).to_string())
    print("\n--- triagem para a LLM ---")
    print(saida["motivo_llm"].value_counts().to_string())
    marcados = saida["precisa_llm"] == "Sim"
    print(f"\n  precisa_llm = Sim: {int(marcados.sum())} de {len(saida)} "
          f"({100 * marcados.mean():.1f}%)")


def exportar(saida_path: Path, usar_pdf: bool, workers: int) -> pd.DataFrame:
    conn = obter_conexao()
    try:
        df = carregar(conn)
    finally:
        conn.close()
    print(f"{len(df)} extracoes no banco ({df['cnpj'].nunique()} fundos distintos)")

    resultado = montar_saida(df, recortar(df, usar_pdf, workers))
    saida_path.parent.mkdir(parents=True, exist_ok=True)
    resultado.to_excel(saida_path, index=False)
    print(f"\nGravado: {saida_path}")
    imprimir_resumo(resultado)
    return resultado


def _argumento(argv, nome, padrao=None):
    return argv[argv.index(nome) + 1] if nome in argv and argv.index(nome) + 1 < len(argv) else padrao


if __name__ == "__main__":
    _argv = sys.argv[1:]
    _workers = int(_argumento(_argv, "--workers", WORKERS_PADRAO))
    _padrao = f"base_opiniao_{datetime.now():%Y%m%d_%H%M}.xlsx"
    _saida = Path(_argumento(_argv, "--saida", str(config.BASE_DIR / "exports" / _padrao)))
    exportar(_saida, usar_pdf="--sem-pdf" not in _argv, workers=_workers)
