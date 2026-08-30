"""Configuracao do projeto - tudo em um arquivo unico, sem classes.

Qualquer caminho ou URL usado pelos pipelines/frontend vem daqui.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DB_DIR = BASE_DIR / "db"
DB_PATH = DB_DIR / "cotas.db"

RAW_DIR = BASE_DIR / "pipeline" / "raw"

# --- CVM: Registro Fundo Classe (cadastro de fundos) ---
CVM_REGISTRO_FUNDO_CLASSE_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip"

# --- CVM: Historico de prestadores (cadastro legado, chaveado por CNPJ_FUNDO) ---
CVM_CAD_FI_HIST_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi_hist.zip"

# --- CVM: CDA (Composicao e Diversificacao de Aplicacoes), Bloco 2 ---
CVM_CDA_ZIP_URL_TEMPLATE = "https://dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS/cda_fi_{competencia}.zip"

# --- CVM: Documentos Eventuais (fonte das Demonstracoes Financeiras e opiniao do auditor) ---
# Um arquivo por ano-calendario de entrega; o mesmo ano_referencia de uma DF pode ser
# entregue/retificado no arquivo do ano atual ou no do ano anterior.
CVM_EVENTUAL_FI_URL_TEMPLATE = "https://dados.cvm.gov.br/dados/FI/DOC/EVENTUAL/DADOS/eventual_fi_{ano}.csv"
TIPOS_DOC_DEMONSTRACAO_FINANCEIRA = ("DEMONST CONTAB", "DF", "DF ANUAL FIAGRO", "DF ANUAL FII")

# --- CVM: FII - Demonstracoes Financeiras (dataset proprio, fora do eventual) ---
# Ja vem com o parecer do auditor pre-classificado pela CVM (campo Parecer_Auditor)
# e o link direto do documento (Link_Download) - fonte melhor que o eventual pra FII,
# que la vem sempre com RESULTADO_AUDITORIA vazio.
CVM_DFIN_FII_URL_TEMPLATE = "https://dados.cvm.gov.br/dados/FII/DOC/DFIN/DADOS/dfin_fii_{ano}.csv"

# Tipos de documento usados so como FONTE PARA EXTRACAO DE OPINIAO (modulo de IA) -
# nao entram no calculo de atraso/prazo de demonstracoes (essa lista fica em
# TIPOS_DOC_DEMONSTRACAO_FINANCEIRA, acima). "PARECER AUD." e um documento a parte,
# normalmente so o parecer do auditor (menor, mais direto que a DF inteira).
TIPOS_DOC_FONTE_OPINIAO = ("PARECER AUD.", "DF ANUAL FII", "DF ANUAL FIAGRO", "DF", "DEMONST CONTAB")

CVM_CSV_SEPARATOR = ";"
CVM_CSV_ENCODING = "latin-1"

# Situacoes de fundo consideradas validas (comparar sempre em maiusculas,
# a fonte usa Title Case: "Em Funcionamento Normal").
SITUACOES_FUNDO_VALIDAS = ("EM FUNCIONAMENTO NORMAL", "FASE PRÉ-OPERACIONAL")

# Exclusao de administradores Bradesco/BEM - por substring/prefixo, nao lista fechada.
ADMINISTRADORES_EXCLUIDOS_SUBSTRINGS = ("BRADESCO",)
ADMINISTRADORES_EXCLUIDOS_PREFIXOS = ("BEM -", "BEM-")

# Logo Bradesco usado no frontend (projeto irmao "Fato Relevante").
BRADESCO_LOGO_PATH = Path(r"C:\Users\CLIENTE\Documents\Fato Relevante\assets\bradesco_logo_white.png")