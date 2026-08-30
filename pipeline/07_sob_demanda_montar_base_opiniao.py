"""Monta a base de FONTES de opiniao do auditor - passo que roda ANTES da
extracao de texto do PDF (06_sob_demanda_extrair_texto_opiniao.py).

Junta duas origens:

1. Documentos EVENTUAL (mesmo arquivo do 03_semanal_update_demonstracoes.py, ja
   cacheado em pipeline/raw/), mas filtrado por config.TIPOS_DOC_FONTE_OPINIAO
   ("PARECER AUD.", "DF ANUAL FII", "DF ANUAL FIAGRO", "DF") - inclui "PARECER
   AUD.", que NAO entra na tabela `demonstracoes` (essa e so pro calculo de
   atraso/prazo). E o documento mais direto: normalmente e so o parecer do
   auditor sozinho, nao a DF inteira.

2. Dataset FII/DOC/DFIN da CVM (dfin_fii_AAAA.csv) - especifico de fundo
   imobiliario, e ja vem com o parecer do auditor PRE-CLASSIFICADO pela propria
   CVM (campo Parecer_Auditor: "Sem ressalva e sem enfase" / "Com ressalva" /
   "Abstencao de opiniao" / etc.) - resolve de graca o buraco que RESULTADO_AUDITORIA
   sempre vazio deixava pros FII no eventual.

Grava tudo em `fontes_opiniao_auditor`, 1 linha por (fundo, ano, origem) - o
proximo passo (extracao de PDF) decide a prioridade entre as fontes disponiveis
por fundo/ano (ver ORDEM_PRIORIDADE_ORIGEM).

Nao mexe em `demonstracoes` nem em classificacao_risco/situacao de atraso -
essa base e so insumo pro modulo de IA.

Uso:
    python pipeline/07_sob_demanda_montar_base_opiniao.py
"""

import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from pipeline.utils import (  # noqa: F401
    ORDEM_PRIORIDADE_ORIGEM,
    normalizar_cnpj,
    normalizar_texto,
    obter_conexao,
    registrar_log,
)

NOME_PIPELINE = "montar_base_opiniao"


def _origem_eventual(tipo_doc, prefixo="EVENTUAL"):
    return prefixo + "_" + tipo_doc.strip().replace(" ANUAL ", "_ANUAL_").replace(" ", "_").replace(".", "")


ORIGEM_ARQUIVO_MANUAL_OPINIAO_PRONTA = "ARQUIVO_MANUAL_OPINIAO_PRONTA"


def _para_int_nativo(serie):
    """Converte uma serie pandas Int64 (nullable) para int/None nativos do Python.

    O sqlite3 do Python nao sabe bindar numpy.int64 como INTEGER - como o tipo
    expoe o protocolo de buffer (e um escalar/array 0-d do numpy), o driver
    grava o valor cru em memoria como BLOB em vez de converter pra INTEGER.
    Isso silenciosamente corrompe ano_referencia pra quem usa .astype("Int64")
    (mantido aqui so pra suportar nulo antes da conversao final)."""
    return serie.apply(lambda v: int(v) if pd.notna(v) else None)


def tratar_arquivo_manual(df):
    """Le um CSV no mesmo layout do eventual_fi (11 colunas), mas fornecido
    manualmente (ex: exportado a mao do portal da CVM) - layout identico, exceto
    a data em DD/MM/AAAA (o eventual oficial da CVM vem em AAAA-MM-DD).

    Duas situacoes:
    - TP_DOC preenchido e um dos TIPOS_DOC_FONTE_OPINIAO -> mesmo tratamento do
      eventual oficial (so filtro por TP_DOC), origem prefixada com "MANUAL_".
    - TP_DOC vazio mas RESULTADO_AUDITORIA preenchido -> parecem linhas vindas do
      DFIN coladas nesse arquivo sem TP_DOC; tratadas como origem separada com a
      opiniao ja pronta (nao searchable por cabecalho, ja vem classificada)."""
    df = df.copy()
    df["fundo_cnpj"] = df["CNPJ_FUNDO_CLASSE"].apply(normalizar_cnpj)
    df["nome_fundo"] = df["DENOM_SOCIAL"].apply(normalizar_texto)
    df["ano_referencia"] = _para_int_nativo(pd.to_datetime(df["DT_COMPTC"], dayfirst=True, errors="coerce").dt.year.astype("Int64"))
    df["data_entrega"] = pd.to_datetime(df["DT_RECEB"], dayfirst=True, errors="coerce")
    df["link_arquivo"] = df["LINK_ARQ"]
    df["versao"] = None

    com_tipo = df[df["TP_DOC"].isin(config.TIPOS_DOC_FONTE_OPINIAO)].copy()
    com_tipo["origem"] = com_tipo["TP_DOC"].apply(lambda t: _origem_eventual(t, prefixo="MANUAL"))
    com_tipo["opiniao_estruturada"] = None

    sem_tipo_com_opiniao = df[df["TP_DOC"].isna() & df["RESULTADO_AUDITORIA"].notna()].copy()
    sem_tipo_com_opiniao["origem"] = ORIGEM_ARQUIVO_MANUAL_OPINIAO_PRONTA
    sem_tipo_com_opiniao["opiniao_estruturada"] = sem_tipo_com_opiniao["RESULTADO_AUDITORIA"]

    resultado = pd.concat([com_tipo, sem_tipo_com_opiniao], ignore_index=True)
    colunas = ["fundo_cnpj", "nome_fundo", "ano_referencia", "origem", "link_arquivo", "data_entrega", "versao", "opiniao_estruturada"]
    resultado["data_entrega"] = resultado["data_entrega"].dt.strftime("%Y-%m-%d")
    return resultado[colunas].where(pd.notnull(resultado[colunas]), None)


def ler_csv_eventual(ano):
    caminho = config.RAW_DIR / f"eventual_fi_{ano}.csv"
    if not caminho.exists():
        print(f"  {caminho.name} nao esta em cache - baixando...")
        config.RAW_DIR.mkdir(parents=True, exist_ok=True)
        url = config.CVM_EVENTUAL_FI_URL_TEMPLATE.format(ano=ano)
        resposta = requests.get(url, timeout=120)
        resposta.raise_for_status()
        caminho.write_bytes(resposta.content)
    return pd.read_csv(caminho, sep=config.CVM_CSV_SEPARATOR, encoding=config.CVM_CSV_ENCODING, dtype=str)


def tratar_eventual(df):
    """So o filtro por TP_DOC (config.TIPOS_DOC_FONTE_OPINIAO) - de proposito, sem
    validar CNPJ contra `fundos`, sem descartar linha com campo nulo/sem link e sem
    dedup de retificadora. O resto passa como veio do CVM."""
    df = df[df["TP_DOC"].isin(config.TIPOS_DOC_FONTE_OPINIAO)].copy()

    df["fundo_cnpj"] = df["CNPJ_FUNDO_CLASSE"].apply(normalizar_cnpj)
    df["nome_fundo"] = df["DENOM_SOCIAL"].apply(normalizar_texto)
    df["ano_referencia"] = _para_int_nativo(pd.to_datetime(df["DT_COMPTC"], errors="coerce").dt.year.astype("Int64"))
    df["data_entrega"] = pd.to_datetime(df["DT_RECEB"], errors="coerce")
    df["origem"] = df["TP_DOC"].apply(_origem_eventual)
    df["link_arquivo"] = df["LINK_ARQ"]
    df["versao"] = None
    df["opiniao_estruturada"] = None

    colunas = ["fundo_cnpj", "nome_fundo", "ano_referencia", "origem", "link_arquivo", "data_entrega", "versao", "opiniao_estruturada"]
    df["data_entrega"] = df["data_entrega"].dt.strftime("%Y-%m-%d")
    return df[colunas].where(pd.notnull(df[colunas]), None)


def ler_csv_dfin(ano):
    caminho = config.RAW_DIR / f"dfin_fii_{ano}.csv"
    print(f"  Baixando {config.CVM_DFIN_FII_URL_TEMPLATE.format(ano=ano)}")
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    url = config.CVM_DFIN_FII_URL_TEMPLATE.format(ano=ano)
    resposta = requests.get(url, timeout=120)
    resposta.raise_for_status()
    caminho.write_bytes(resposta.content)
    return pd.read_csv(caminho, sep=config.CVM_CSV_SEPARATOR, encoding=config.CVM_CSV_ENCODING, dtype=str)


def tratar_dfin(df):
    """Mesma regra do tratar_eventual: NAO valida o CNPJ contra `fundos`.

    Validar aqui descartava FII com DF publicada so por estarem fora do cadastro
    ativo (cancelado/liquidado/incorporado, ou administrador excluido) - e o
    descarte acontecia ANTES de gravar, entao nao dava pra recuperar depois
    soltando o escopo da extracao. Esta base e o insumo bruto do modulo de IA;
    quem decide o recorte e quem consome."""
    df = df.copy()
    df["fundo_cnpj"] = df["CNPJ_Fundo_Classe"].apply(normalizar_cnpj)
    df["nome_fundo"] = df["Nome_Fundo_Classe"].apply(normalizar_texto)
    df = df[df["fundo_cnpj"].notna()]

    df["ano_referencia"] = pd.to_datetime(df["Data_Referencia"], errors="coerce").dt.year
    df["data_entrega"] = pd.to_datetime(df["Data_Entrega"], errors="coerce")
    df = df[df["ano_referencia"].notna() & df["Link_Download"].notna()]
    df["ano_referencia"] = df["ano_referencia"].astype(int)
    df["versao"] = pd.to_numeric(df["Versao"], errors="coerce").fillna(1).astype(int)

    df["origem"] = "DFIN_FII"
    df["link_arquivo"] = df["Link_Download"]
    df["opiniao_estruturada"] = df["Parecer_Auditor"]

    # Fica so a versao mais alta por (fundo, ano) - retificacoes tem versao maior.
    df = df.sort_values("versao").drop_duplicates(subset=["fundo_cnpj", "ano_referencia"], keep="last")

    colunas = ["fundo_cnpj", "nome_fundo", "ano_referencia", "origem", "link_arquivo", "data_entrega", "versao", "opiniao_estruturada"]
    df["data_entrega"] = df["data_entrega"].dt.strftime("%Y-%m-%d")
    return df[colunas].where(pd.notnull(df[colunas]), None)


def garantir_coluna_nome(conn):
    """Cria nome_fundo em banco criado antes dela existir - producao nao e recriada."""
    existentes = {linha[1] for linha in conn.execute("PRAGMA table_info(fontes_opiniao_auditor)")}
    if existentes and "nome_fundo" not in existentes:
        conn.execute("ALTER TABLE fontes_opiniao_auditor ADD COLUMN nome_fundo TEXT")
        conn.commit()


def persistir(conn, df):
    if df.empty:
        return 0, 0
    cursor = conn.cursor()
    chaves_existentes = set(cursor.execute("SELECT fundo_cnpj, ano_referencia, origem FROM fontes_opiniao_auditor"))
    linhas = list(df.itertuples(index=False, name=None))
    chaves_novo_lote = {(f, a, o) for f, _n, a, o, *_ in linhas}
    inseridas = len(chaves_novo_lote - chaves_existentes)
    atualizadas = len(chaves_novo_lote & chaves_existentes)

    cursor.executemany(
        """
        INSERT INTO fontes_opiniao_auditor
            (fundo_cnpj, nome_fundo, ano_referencia, origem, link_arquivo, data_entrega, versao, opiniao_estruturada)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (fundo_cnpj, ano_referencia, origem) DO UPDATE SET
            nome_fundo = excluded.nome_fundo,
            link_arquivo = excluded.link_arquivo,
            data_entrega = excluded.data_entrega,
            versao = excluded.versao,
            opiniao_estruturada = excluded.opiniao_estruturada,
            atualizado_em = datetime('now', 'localtime')
        """,
        linhas,
    )
    conn.commit()
    return inseridas, atualizadas


def montar_base(arquivo_manual=None):
    inicio = time.monotonic()
    conn = obter_conexao()
    try:
        garantir_coluna_nome(conn)
        total_inseridas = total_atualizadas = total_lidas = 0

        if arquivo_manual:
            print(f"== Arquivo manual ({arquivo_manual}) ==")
            bruto = pd.read_csv(arquivo_manual, sep=config.CVM_CSV_SEPARATOR, encoding=config.CVM_CSV_ENCODING, dtype=str)
            tratado = tratar_arquivo_manual(bruto)
            inseridas, atualizadas = persistir(conn, tratado)
            print(f"  {len(bruto)} linhas lidas, {len(tratado)} aproveitadas, "
                  f"{inseridas} novas, {atualizadas} atualizadas")
            total_lidas += len(bruto)
            total_inseridas += inseridas
            total_atualizadas += atualizadas

        print("== Eventual (PARECER AUD. / DF ANUAL FII / DF ANUAL FIAGRO / DF / DEMONST CONTAB) ==")
        for ano in (2024, 2025, 2026):
            bruto = ler_csv_eventual(ano)
            tratado = tratar_eventual(bruto)
            inseridas, atualizadas = persistir(conn, tratado)
            print(f"  {ano}: {len(bruto)} linhas lidas, {len(tratado)} aproveitadas, "
                  f"{inseridas} novas, {atualizadas} atualizadas")
            total_lidas += len(bruto)
            total_inseridas += inseridas
            total_atualizadas += atualizadas

        print("== DFIN FII (dados.cvm.gov.br/dataset/fii-doc-dfin) ==")
        for ano in (2024, 2025, 2026):
            bruto = ler_csv_dfin(ano)
            tratado = tratar_dfin(bruto)
            inseridas, atualizadas = persistir(conn, tratado)
            print(f"  {ano}: {len(bruto)} linhas lidas, {len(tratado)} aproveitadas, "
                  f"{inseridas} novas, {atualizadas} atualizadas")
            total_lidas += len(bruto)
            total_inseridas += inseridas
            total_atualizadas += atualizadas

        registrar_log(
            conn, NOME_PIPELINE, "fontes_opiniao_auditor", "SUCESSO",
            linhas_lidas=total_lidas, linhas_inseridas=total_inseridas,
            linhas_atualizadas=total_atualizadas, duracao_segundos=time.monotonic() - inicio,
        )

        print()
        print("== Resumo por origem (fontes_opiniao_auditor) ==")
        for origem, qtd in conn.execute("SELECT origem, COUNT(*) FROM fontes_opiniao_auditor GROUP BY origem ORDER BY 2 DESC"):
            print(f"  {origem}: {qtd}")

        fundos_cobertos = conn.execute("SELECT COUNT(DISTINCT fundo_cnpj) FROM fontes_opiniao_auditor").fetchone()[0]
        print(f"\nFundos distintos cobertos por essa base: {fundos_cobertos}")

    except Exception as exc:
        registrar_log(
            conn, NOME_PIPELINE, "fontes_opiniao_auditor", "ERRO",
            mensagem_erro=str(exc), duracao_segundos=time.monotonic() - inicio,
        )
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    _arquivo_manual = None
    _argv = sys.argv[1:]
    if "--arquivo-manual" in _argv:
        _idx = _argv.index("--arquivo-manual")
        if _idx + 1 < len(_argv):
            _arquivo_manual = _argv[_idx + 1]

    montar_base(arquivo_manual=_arquivo_manual)
