"""Funcoes utilitarias compartilhadas pelos pipelines (sem classes)."""

import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

_NAO_DIGITO = re.compile(r"\D")
_ESPACOS_MULTIPLOS = re.compile(r"\s+")

# Ordem de preferencia entre as origens de fontes_opiniao_auditor quando um
# fundo/ano tem mais de uma disponivel - quanto menor, melhor. Compartilhada entre
# 07_sob_demanda_montar_base_opiniao.py (quem grava as origens) e
# 06_sob_demanda_extrair_texto_opiniao.py (quem escolhe qual processar).
ORDEM_PRIORIDADE_ORIGEM = {
    "ARQUIVO_MANUAL_OPINIAO_PRONTA": 0,  # ja vem classificada, nem precisa abrir PDF
    "EVENTUAL_PARECER_AUD": 1,
    "MANUAL_PARECER_AUD": 1,
    "DFIN_FII": 2,
    "EVENTUAL_DF_ANUAL_FII": 3,
    "EVENTUAL_DF_ANUAL_FIAGRO": 3,
    "MANUAL_DF_ANUAL_FII": 3,
    "MANUAL_DF_ANUAL_FIAGRO": 3,
    "EVENTUAL_DF": 4,
    "MANUAL_DF": 4,
    "EVENTUAL_DEMONST_CONTAB": 5,
    "MANUAL_DEMONST_CONTAB": 5,
}


def obter_conexao():
    """Abre uma conexao com o banco (cria a pasta db/ se preciso)."""
    config.DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def normalizar_cnpj(valor):
    """Remove pontuacao e valida 14 digitos. Retorna None se invalido/vazio/NaN."""
    if not isinstance(valor, str) or not valor:
        return None
    digitos = _NAO_DIGITO.sub("", valor)
    if len(digitos) != 14:
        return None
    return digitos


def normalizar_texto(valor):
    """Remove espacos nas pontas e colapsa espacos internos. None para NaN/nao-string."""
    if not isinstance(valor, str):
        return None
    texto = _ESPACOS_MULTIPLOS.sub(" ", valor.strip())
    return texto or None


def registrar_log(conn, nome_pipeline, nome_base_competencia, status, competencia=None,
                   linhas_lidas=0, linhas_processadas=0, linhas_inseridas=0,
                   linhas_atualizadas=0, linhas_ignoradas=0, duracao_segundos=0.0,
                   mensagem_erro=None):
    """Grava um registro em logs_pipeline e atualiza a tabela competencias."""
    conn.execute(
        """
        INSERT INTO logs_pipeline
            (nome_pipeline, status, linhas_lidas, linhas_processadas, linhas_inseridas,
             linhas_atualizadas, linhas_ignoradas, duracao_segundos, mensagem_erro, competencia)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (nome_pipeline, status, linhas_lidas, linhas_processadas, linhas_inseridas,
         linhas_atualizadas, linhas_ignoradas, duracao_segundos, mensagem_erro, competencia),
    )
    if competencia:
        conn.execute(
            """
            INSERT INTO competencias (nome_base, competencia, status)
            VALUES (?, ?, ?)
            ON CONFLICT (nome_base, competencia) DO UPDATE SET
                status = excluded.status,
                data_processamento = datetime('now', 'localtime')
            """,
            (nome_base_competencia, competencia, "CONCLUIDA" if status == "SUCESSO" else "ERRO"),
        )
    conn.commit()

    if status == "SUCESSO":
        print(
            f"[{nome_pipeline}] SUCESSO em {duracao_segundos:.2f}s - "
            f"lidas={linhas_lidas} processadas={linhas_processadas} "
            f"inseridas={linhas_inseridas} atualizadas={linhas_atualizadas} "
            f"ignoradas={linhas_ignoradas}"
        )
    else:
        print(f"[{nome_pipeline}] ERRO: {mensagem_erro}")