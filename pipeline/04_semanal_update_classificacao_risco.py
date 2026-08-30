"""Pipeline de classificacao de risco - heuristica baseada so na opiniao da DF.

NAO e um modulo de IA - e um sinal simples, transparente e 100% derivado de dado
real ja no banco: a opiniao do auditor na Demonstracao Financeira mais recente
(demonstracoes).

Opiniao do auditor (DF mais recente):
  ALTO  = Abstencao de opiniao ou opiniao Adversa
  MEDIO = Ressalva
  (Sem ressalva/Dispensado nao elevam o risco - fundo fica sem classificacao)

Sem download - recalcula a partir do que ja esta no SQLite.

Frequencia: SEMANAL. Rodar por ultimo, depois de 03_semanal_update_demonstracoes.py
(e quem alimenta o sinal usado aqui).

Uso:
    python pipeline/04_semanal_update_classificacao_risco.py
"""

import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.utils import obter_conexao, registrar_log

NOME_PIPELINE = "update_classificacao_risco"
NOME_BASE_COMPETENCIA = "classificacao_risco"

OPINIAO_PARA_SEVERIDADE = {"RESSALVA": "MEDIO", "ABSTENCAO": "ALTO", "ADVERSA": "ALTO"}
OPINIAO_LABEL = {"RESSALVA": "Ressalva", "ABSTENCAO": "Abstencao de opiniao", "ADVERSA": "Opiniao adversa"}


def classificar_por_opiniao(conn):
    """Opiniao do auditor da DF mais recente por fundo - so as que pesam no risco."""
    df = pd.read_sql_query(
        """
        SELECT fundo_cnpj, ano_referencia, opiniao_auditor
        FROM demonstracoes
        WHERE opiniao_auditor IN ('RESSALVA', 'ABSTENCAO', 'ADVERSA')
        """,
        conn,
    )
    if df.empty:
        return []

    mais_recente = df.sort_values("ano_referencia").groupby("fundo_cnpj").tail(1)
    return [
        (
            OPINIAO_PARA_SEVERIDADE[linha.opiniao_auditor],
            f"{OPINIAO_LABEL[linha.opiniao_auditor]} na DF de {linha.ano_referencia}",
            linha.fundo_cnpj,
        )
        for linha in mais_recente.itertuples(index=False)
    ]


def persistir(conn, classificacoes):
    if not classificacoes:
        return 0
    cursor = conn.cursor()
    cursor.executemany(
        "UPDATE fundos SET classificacao_risco = ?, motivo_classificacao_risco = ? WHERE cnpj = ?",
        classificacoes,
    )
    conn.commit()
    return cursor.rowcount


def atualizar_classificacao_risco():
    inicio = time.monotonic()
    competencia = date.today().strftime("%Y%m")
    conn = obter_conexao()

    try:
        classificacoes = classificar_por_opiniao(conn)
        atualizadas = persistir(conn, classificacoes)

        registrar_log(
            conn, NOME_PIPELINE, NOME_BASE_COMPETENCIA, "SUCESSO", competencia=competencia,
            linhas_processadas=len(classificacoes),
            linhas_inseridas=0, linhas_atualizadas=len(classificacoes),
            linhas_ignoradas=0, duracao_segundos=time.monotonic() - inicio,
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
    atualizar_classificacao_risco()
