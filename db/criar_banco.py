"""Cria o banco SQLite com todas as tabelas do sistema, caso ainda nao exista.

Uso:
    python db/criar_banco.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

SQL_CRIACAO = """
CREATE TABLE IF NOT EXISTS fundos (
    cnpj TEXT PRIMARY KEY,
    cd_cvm TEXT,
    denominacao_social TEXT NOT NULL,
    tp_fundo TEXT,
    classe TEXT,
    classe_anbima TEXT,
    situacao TEXT NOT NULL,
    id_registro_fundo TEXT,
    id_registro_classe TEXT,
    fundo_cnpj_pai TEXT,
    tipo_classe TEXT,
    data_registro DATE,
    data_constituicao DATE,
    data_cancelamento DATE,
    data_inicio_situacao DATE,
    exercicio_social_inicio DATE,
    exercicio_social_fim DATE,
    condominio TEXT,
    fundo_cotas INTEGER,
    fundo_exclusivo INTEGER,
    publico_alvo TEXT,
    taxa_administracao REAL,
    taxa_performance REAL,
    patrimonio_liquido REAL,
    data_patrimonio_liquido DATE,
    administrador_nome TEXT,
    administrador_cnpj TEXT,
    gestor_nome TEXT,
    gestor_cpf_cnpj TEXT,
    auditor_nome TEXT,
    auditor_cnpj TEXT,
    custodiante_nome TEXT,
    custodiante_cnpj TEXT,
    controlador_nome TEXT,
    controlador_cnpj TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    competencia_referencia TEXT,
    classificacao_risco TEXT,
    motivo_classificacao_risco TEXT,
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    atualizado_em TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS ix_fundos_situacao ON fundos(situacao);
CREATE INDEX IF NOT EXISTS ix_fundos_classificacao_risco ON fundos(classificacao_risco);
CREATE INDEX IF NOT EXISTS ix_fundos_fundo_cnpj_pai ON fundos(fundo_cnpj_pai);
CREATE INDEX IF NOT EXISTS ix_fundos_administrador_nome ON fundos(administrador_nome);

CREATE TABLE IF NOT EXISTS prestadores_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fundo_cnpj TEXT NOT NULL REFERENCES fundos (cnpj),
    prestador_cnpj TEXT,
    tipo_prestador TEXT NOT NULL,
    nome TEXT NOT NULL,
    data_inicio DATE,
    data_fim DATE,
    competencia TEXT NOT NULL,
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE (fundo_cnpj, tipo_prestador, data_inicio, competencia)
);
CREATE INDEX IF NOT EXISTS ix_hist_fundo_cnpj ON prestadores_historico(fundo_cnpj);

CREATE TABLE IF NOT EXISTS cda_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identificador TEXT NOT NULL,
    tipo_no TEXT NOT NULL,
    nome TEXT,
    classe TEXT,
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    atualizado_em TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE (identificador, tipo_no)
);

CREATE TABLE IF NOT EXISTS cda_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    no_origem_id INTEGER NOT NULL REFERENCES cda_nodes (id),
    no_destino_id INTEGER NOT NULL REFERENCES cda_nodes (id),
    valor REAL NOT NULL,
    percentual_pl REAL,
    competencia TEXT NOT NULL,
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE (no_origem_id, no_destino_id, competencia)
);
CREATE INDEX IF NOT EXISTS ix_edges_origem ON cda_edges(no_origem_id);

CREATE TABLE IF NOT EXISTS demonstracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fundo_cnpj TEXT NOT NULL REFERENCES fundos (cnpj),
    ano_referencia INTEGER NOT NULL,
    tipo_demonstracao TEXT,
    opiniao_auditor TEXT,
    arquivo_origem TEXT,
    status TEXT NOT NULL DEFAULT 'PENDENTE',
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    atualizado_em TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE (fundo_cnpj, ano_referencia, tipo_demonstracao)
);

-- Sem FK/NOT NULL de proposito: essa tabela guarda o resultado de um filtro RAW
-- por TP_DOC (ver 07_sob_demanda_montar_base_opiniao.py) - nao valida CNPJ contra
-- `fundos` nem descarta linha incompleta, entao pode ter fundo cancelado/inativo,
-- CNPJ invalido ou campo nulo.
CREATE TABLE IF NOT EXISTS fontes_opiniao_auditor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fundo_cnpj TEXT,
    nome_fundo TEXT,  -- vem do proprio CSV de origem: cobre fundo fora do cadastro
    ano_referencia INTEGER,
    origem TEXT NOT NULL,
    link_arquivo TEXT,
    data_entrega DATE,
    versao INTEGER,
    opiniao_estruturada TEXT,
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    atualizado_em TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE (fundo_cnpj, ano_referencia, origem)
);
CREATE INDEX IF NOT EXISTS ix_fontes_opiniao_fundo ON fontes_opiniao_auditor(fundo_cnpj);

-- Resultado da extracao de texto (06_sob_demanda_extrair_texto_opiniao.py) quando
-- a fonte e fontes_opiniao_auditor (nao demonstracoes) - mesma forma que
-- demonstracoes_extracao, so troca o FK de origem.
CREATE TABLE IF NOT EXISTS fontes_opiniao_extracao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte_opiniao_id INTEGER NOT NULL UNIQUE REFERENCES fontes_opiniao_auditor (id),
    caminho_pdf TEXT,
    numero_paginas INTEGER,
    tamanho_pdf_bytes INTEGER,
    encontrou_secao_opiniao INTEGER NOT NULL DEFAULT 0,
    trecho_opiniao TEXT,
    trecho_opiniao_secao TEXT,
    trecho_base_opiniao TEXT,
    trecho_enfase_outros TEXT,
    secoes_adicionais TEXT,
    titulo_opiniao TEXT,
    titulo_base TEXT,
    tipo_opiniao_detectado TEXT,
    metodo_recorte TEXT,
    metodo_extracao TEXT,
    mensagem_erro TEXT,
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    atualizado_em TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS demonstracoes_extracao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    demonstracao_id INTEGER NOT NULL UNIQUE REFERENCES demonstracoes (id),
    caminho_pdf TEXT,
    numero_paginas INTEGER,
    tamanho_pdf_bytes INTEGER,
    encontrou_secao_opiniao INTEGER NOT NULL DEFAULT 0,
    trecho_opiniao TEXT,
    trecho_opiniao_secao TEXT,
    trecho_base_opiniao TEXT,
    trecho_enfase_outros TEXT,
    secoes_adicionais TEXT,
    titulo_opiniao TEXT,
    titulo_base TEXT,
    tipo_opiniao_detectado TEXT,
    metodo_recorte TEXT,
    metodo_extracao TEXT,
    mensagem_erro TEXT,
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    atualizado_em TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS demonstracoes_ai (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    demonstracao_id INTEGER NOT NULL UNIQUE REFERENCES demonstracoes (id),
    resumo_executivo TEXT,
    principais_riscos TEXT,
    pontos_importantes TEXT,
    classificacao_risco TEXT,
    tipo_opiniao_ia TEXT,
    impacto TEXT,
    modelo_utilizado TEXT,
    prompt_versao TEXT,
    resposta_bruta_json TEXT,
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    atualizado_em TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS fatos_relevantes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fundo_cnpj TEXT NOT NULL REFERENCES fundos (cnpj),
    nome_fundo TEXT,
    titulo TEXT,
    data_referencia DATE,
    categoria TEXT,
    resumo TEXT,
    impacto TEXT,
    plano_acao TEXT,
    arquivo_pdf TEXT,
    texto_extraido TEXT,
    status_ia TEXT,
    origem TEXT NOT NULL DEFAULT 'FATO_RELEVANTE_DB',
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    atualizado_em TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE (fundo_cnpj, data_referencia, arquivo_pdf)
);

CREATE TABLE IF NOT EXISTS logs_pipeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_pipeline TEXT NOT NULL,
    data_execucao TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    status TEXT NOT NULL,
    linhas_lidas INTEGER,
    linhas_processadas INTEGER,
    linhas_inseridas INTEGER,
    linhas_atualizadas INTEGER,
    linhas_ignoradas INTEGER,
    duracao_segundos REAL,
    mensagem_erro TEXT,
    competencia TEXT,
    criado_em TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS competencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_base TEXT NOT NULL,
    competencia TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'CONCLUIDA',
    data_processamento TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    pipeline_log_id INTEGER REFERENCES logs_pipeline (id),
    criado_em TEXT DEFAULT (datetime('now', 'localtime')),
    atualizado_em TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE (nome_base, competencia)
);
"""


# Colunas adicionadas apos a criacao inicial da tabela - ALTER TABLE nao suporta
# "ADD COLUMN IF NOT EXISTS", entao verificamos via PRAGMA antes de aplicar.
COLUNAS_NOVAS_DEMONSTRACOES_AI = {
    "descricao_opiniao_modificada": "TEXT",
    "potencial_risco_investidor": "TEXT",
}


def _migrar_colunas_novas(conn):
    colunas_existentes = {linha[1] for linha in conn.execute("PRAGMA table_info(demonstracoes_ai)")}
    for coluna, tipo in COLUNAS_NOVAS_DEMONSTRACOES_AI.items():
        if coluna not in colunas_existentes:
            conn.execute(f"ALTER TABLE demonstracoes_ai ADD COLUMN {coluna} {tipo}")


def _migrar_prestadores_para_cnpj(conn):
    """Migracao unica: a tabela `prestadores` (catalogo com id substituto) foi
    removida - prestadores_historico passa a guardar o CNPJ do prestador direto
    na coluna prestador_cnpj, sem indirecao por prestador_id."""
    colunas_existentes = {linha[1] for linha in conn.execute("PRAGMA table_info(prestadores_historico)")}
    if "prestador_id" not in colunas_existentes:
        return

    conn.execute("ALTER TABLE prestadores_historico ADD COLUMN prestador_cnpj TEXT")
    conn.execute(
        """
        UPDATE prestadores_historico
        SET prestador_cnpj = (
            SELECT cnpj FROM prestadores WHERE prestadores.id = prestadores_historico.prestador_id
        )
        WHERE prestador_id IS NOT NULL
        """
    )
    conn.execute("ALTER TABLE prestadores_historico DROP COLUMN prestador_id")
    conn.execute("DROP TABLE IF EXISTS prestadores")


def _migrar_remover_monitoramento(conn):
    """Migracao unica: tabela `monitoramento` removida do schema (sem uso ainda)."""
    conn.execute("DROP TABLE IF EXISTS monitoramento")


def _migrar_fontes_opiniao_sem_validacao(conn):
    """Migracao unica: fontes_opiniao_auditor nasceu com FK pra fundos e colunas
    NOT NULL (versao com filtro+validacao de CNPJ). Depois virou so um filtro RAW
    por TP_DOC, sem validar CNPJ - as constraints antigas bloqueariam isso, entao
    recria a tabela sem elas. SQLite nao suporta DROP CONSTRAINT, por isso o drop+recreate."""
    colunas = conn.execute("PRAGMA table_info(fontes_opiniao_auditor)").fetchall()
    if not colunas:
        return
    coluna_fundo_cnpj = next((c for c in colunas if c[1] == "fundo_cnpj"), None)
    if coluna_fundo_cnpj is None or coluna_fundo_cnpj[3] == 0:  # notnull == 0 -> ja migrado
        return
    conn.execute("DROP TABLE fontes_opiniao_auditor")
    conn.executescript(SQL_CRIACAO)  # recria com o schema atual (ja sem NOT NULL/FK)


def criar_banco():
    """Cria o arquivo do banco e todas as tabelas, se ainda nao existirem."""
    config.DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.executescript(SQL_CRIACAO)
    _migrar_colunas_novas(conn)
    _migrar_prestadores_para_cnpj(conn)
    _migrar_remover_monitoramento(conn)
    _migrar_fontes_opiniao_sem_validacao(conn)
    conn.commit()
    conn.close()
    print(f"Banco criado/verificado em: {config.DB_PATH}")


if __name__ == "__main__":
    criar_banco()