"""Pipeline de atualizacao de Demonstracoes Financeiras (documentos eventuais da CVM).

Le o arquivo anual de documentos eventuais (eventual_fi_AAAA.csv), filtra os tipos de
documento que sao Demonstracoes Financeiras/Contabeis e extrai a opiniao do auditor
(coluna RESULTADO_AUDITORIA). Sempre processa o ano atual e o ano anterior - a DF de um
ano_referencia pode ser entregue (ou retificada) em qualquer um dos dois arquivos.

Nao baixa nem interpreta o PDF em si - isso fica para o futuro modulo de IA
(demonstracoes_ai). Aqui so registramos o fato "existe uma DF, com esta opiniao".

Alem disso, sincroniza um marcador sintetico (tipo_demonstracao NOVO/DENTRO_DO_PRAZO/
ATRASO) pra todo fundo cuja DF do exercicio mais recente ainda nao esta no banco -
ver sincronizar_situacao_df().

Frequencia: SEMANAL. Depende de `fundos` ja populada (01_diario_update_registro_fundo.py).

Uso:
    python pipeline/03_semanal_update_demonstracoes.py
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from pipeline.utils import normalizar_cnpj, obter_conexao, registrar_log

NOME_PIPELINE = "update_demonstracoes"
NOME_BASE_COMPETENCIA = "demonstracoes_eventual"
NOME_BASE_FUNDOS_NOVOS = "demonstracoes_situacao_df"

# Todo fundo recebe um estado sintetico pra sinalizar a situacao da DF mais
# recente exigivel (mesmo quando ja existe DF real de anos anteriores):
#   NOVO            = o exercicio atual e o primeiro do fundo (ainda nao fechou nenhum)
#   DENTRO_DO_PRAZO = ja fechou o exercicio mais recente, dentro dos 3 meses de prazo da CVM
#   ATRASO          = passou do prazo de entrega (3 meses apos o fechamento) e continua sem DF
# Se ja existe uma DF real cobrindo o exercicio mais recente, nao ha marcador -
# o historico real fala por si.
#
# Fonte preferencial: exercicio_social_inicio/fim de `fundos` (ciclo de exercicio
# atual, registrado pela CVM) - o exercicio anterior (o que exige DF) termina no
# dia anterior ao inicio do ciclo atual. Quando esse campo ainda nao existe (fundo
# muito recente, cadastro incompleto), cai no fallback por dias corridos desde a
# constituicao (so cobre NOVO/ATRASO - fundo com DF real e sem exercicio_social_inicio
# nao e reavaliado, pra nao arriscar falso positivo por falta de dado).
DIAS_JANELA_FUNDO_NOVO = 365
DIAS_PRAZO_ENTREGA_DF = 90
DIAS_LIMITE_ATRASO = DIAS_JANELA_FUNDO_NOVO + DIAS_PRAZO_ENTREGA_DF

TIPO_DEMONSTRACAO_NOVO = "NOVO"
CODIGO_OPINIAO_NOVO = "NOVO"
TIPO_DEMONSTRACAO_DENTRO_DO_PRAZO = "DENTRO_DO_PRAZO"
CODIGO_OPINIAO_DENTRO_DO_PRAZO = "DENTRO_DO_PRAZO"
TIPO_DEMONSTRACAO_ATRASO = "ATRASO"
CODIGO_OPINIAO_ATRASO = "ATRASO"
MARCADORES_SINTETICOS = (TIPO_DEMONSTRACAO_NOVO, TIPO_DEMONSTRACAO_DENTRO_DO_PRAZO, TIPO_DEMONSTRACAO_ATRASO)

# Prefixos (minusculo) do texto bruto de RESULTADO_AUDITORIA -> codigo canonico.
# "OUTRO" e o fallback para variantes desconhecidas, nunca derruba o pipeline.
_PREFIXOS_OPINIAO = (
    ("sem ressalva", "SEM_RESSALVA"),
    ("com ressalva", "RESSALVA"),
    ("abstenç", "ABSTENCAO"),
    ("abstenc", "ABSTENCAO"),
    ("advers", "ADVERSA"),
    ("dispensado", "DISPENSADO"),
)


def normalizar_opiniao(texto):
    if not isinstance(texto, str) or not texto.strip():
        return None
    texto_normalizado = texto.strip().lower()
    for prefixo, codigo in _PREFIXOS_OPINIAO:
        if texto_normalizado.startswith(prefixo):
            return codigo
    return "OUTRO"


def baixar(ano):
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    url = config.CVM_EVENTUAL_FI_URL_TEMPLATE.format(ano=ano)
    destino = config.RAW_DIR / f"eventual_fi_{ano}.csv"

    print(f"Baixando documentos eventuais de {url}")
    response = requests.get(url, stream=True, timeout=120)
    response.raise_for_status()
    with open(destino, "wb") as arquivo:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            arquivo.write(chunk)
    return destino


def ler_csv(caminho):
    df = pd.read_csv(caminho, sep=config.CVM_CSV_SEPARATOR, encoding=config.CVM_CSV_ENCODING, dtype=str)
    print(f"{caminho.name} lido: {len(df)} linhas, {len(df.columns)} colunas")
    return df


def tratar(df, cnpjs_validos):
    df = df[df["TP_DOC"].isin(config.TIPOS_DOC_DEMONSTRACAO_FINANCEIRA)].copy()
    linhas_antes = len(df)

    df["fundo_cnpj"] = df["CNPJ_FUNDO_CLASSE"].apply(normalizar_cnpj)
    df = df[df["fundo_cnpj"].notna() & df["fundo_cnpj"].isin(cnpjs_validos)]

    df["ano_referencia"] = pd.to_datetime(df["DT_COMPTC"], errors="coerce").dt.year
    df["data_recebimento"] = pd.to_datetime(df["DT_RECEB"], errors="coerce")
    df = df[df["ano_referencia"].notna() & df["data_recebimento"].notna()]
    df["ano_referencia"] = df["ano_referencia"].astype(int)

    df["tipo_demonstracao"] = df["TP_DOC"].str.strip()
    df["opiniao_auditor"] = df["RESULTADO_AUDITORIA"].apply(normalizar_opiniao)
    df["arquivo_origem"] = df["LINK_ARQ"]

    linhas_ignoradas = linhas_antes - len(df)

    # Uma retificadora substitui a entrega anterior: fica so a mais recente por
    # (fundo, ano_referencia, tipo_demonstracao) - mesma chave unica da tabela.
    df = df.sort_values("data_recebimento").drop_duplicates(
        subset=["fundo_cnpj", "ano_referencia", "tipo_demonstracao"], keep="last"
    )

    colunas = ["fundo_cnpj", "ano_referencia", "tipo_demonstracao", "opiniao_auditor", "arquivo_origem"]
    return df[colunas].where(pd.notnull(df[colunas]), None), linhas_ignoradas


def persistir(conn, df):
    if df.empty:
        return 0, 0

    cursor = conn.cursor()
    chaves_existentes = set(
        cursor.execute("SELECT fundo_cnpj, ano_referencia, tipo_demonstracao FROM demonstracoes")
    )

    linhas = list(df.itertuples(index=False, name=None))
    chaves_novo_lote = {(fundo_cnpj, ano, tipo) for fundo_cnpj, ano, tipo, _, _ in linhas}
    inseridas = len(chaves_novo_lote - chaves_existentes)
    atualizadas = len(chaves_novo_lote & chaves_existentes)

    cursor.executemany(
        """
        INSERT INTO demonstracoes (fundo_cnpj, ano_referencia, tipo_demonstracao, opiniao_auditor, arquivo_origem)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (fundo_cnpj, ano_referencia, tipo_demonstracao) DO UPDATE SET
            opiniao_auditor = excluded.opiniao_auditor,
            arquivo_origem = excluded.arquivo_origem,
            atualizado_em = datetime('now', 'localtime')
        """,
        linhas,
    )
    conn.commit()
    return inseridas, atualizadas


def processar_ano(conn, ano, cnpjs_validos):
    inicio = time.monotonic()
    competencia = str(ano)
    try:
        caminho = baixar(ano)
        df_bruto = ler_csv(caminho)
        df_tratado, linhas_ignoradas = tratar(df_bruto, cnpjs_validos)
        inseridas, atualizadas = persistir(conn, df_tratado)

        registrar_log(
            conn, NOME_PIPELINE, NOME_BASE_COMPETENCIA, "SUCESSO", competencia=competencia,
            linhas_lidas=len(df_bruto), linhas_processadas=len(df_tratado),
            linhas_inseridas=inseridas, linhas_atualizadas=atualizadas,
            linhas_ignoradas=linhas_ignoradas, duracao_segundos=time.monotonic() - inicio,
        )
    except Exception as exc:
        registrar_log(
            conn, NOME_PIPELINE, NOME_BASE_COMPETENCIA, "ERRO", competencia=competencia,
            mensagem_erro=str(exc), duracao_segundos=time.monotonic() - inicio,
        )
        raise


def _classificar_por_ciclo_exercicio(data_constituicao, exercicio_social_inicio, ultimo_ano_real, hoje):
    """Usa o ciclo de exercicio atual (exercicio_social_inicio) pra achar o
    exercicio mais recente que exige DF - o que terminou no dia anterior ao
    inicio do ciclo em curso."""
    fim_exercicio_anterior = date.fromisoformat(exercicio_social_inicio) - timedelta(days=1)

    if data_constituicao > fim_exercicio_anterior.isoformat():
        # Fundo ainda nao existia quando o exercicio anterior fechou - o ciclo
        # atual e o primeiro dele, sem obrigacao vencida ainda.
        return TIPO_DEMONSTRACAO_NOVO, CODIGO_OPINIAO_NOVO, fim_exercicio_anterior.year

    ano_obrigacao = fim_exercicio_anterior.year
    if ultimo_ano_real is not None and ultimo_ano_real >= ano_obrigacao:
        return None  # ja tem DF real cobrindo o exercicio mais recente

    prazo_entrega = fim_exercicio_anterior + timedelta(days=DIAS_PRAZO_ENTREGA_DF)
    if hoje <= prazo_entrega:
        return TIPO_DEMONSTRACAO_DENTRO_DO_PRAZO, CODIGO_OPINIAO_DENTRO_DO_PRAZO, ano_obrigacao
    return TIPO_DEMONSTRACAO_ATRASO, CODIGO_OPINIAO_ATRASO, ano_obrigacao


def _classificar_por_janela_dias(data_constituicao, ultimo_ano_real, hoje):
    """Fallback quando o fundo ainda nao tem exercicio_social_inicio cadastrado
    (cadastro recente/incompleto) - usa dias corridos desde a constituicao."""
    if ultimo_ano_real is not None:
        return None  # tem DF real mas sem dado de exercicio pra saber se esta desatualizada

    dias_desde_constituicao = (hoje - date.fromisoformat(data_constituicao)).days
    ano_ref = int(data_constituicao[:4])
    if dias_desde_constituicao < DIAS_JANELA_FUNDO_NOVO:
        return TIPO_DEMONSTRACAO_NOVO, CODIGO_OPINIAO_NOVO, ano_ref
    if dias_desde_constituicao > DIAS_LIMITE_ATRASO:
        return TIPO_DEMONSTRACAO_ATRASO, CODIGO_OPINIAO_ATRASO, ano_ref
    return TIPO_DEMONSTRACAO_DENTRO_DO_PRAZO, CODIGO_OPINIAO_DENTRO_DO_PRAZO, ano_ref


def sincronizar_situacao_df(conn):
    """Recalcula o marcador sintetico (NOVO/DENTRO_DO_PRAZO/ATRASO) de cada fundo
    pra sinalizar se a DF do exercicio mais recente esta em dia - mesmo quando ja
    existe DF real de anos anteriores. Remove o marcador de quem passou a ter DF
    real cobrindo o exercicio mais recente."""
    cursor = conn.cursor()
    hoje = date.today()
    placeholders_marcadores = ", ".join("?" for _ in MARCADORES_SINTETICOS)

    ultimo_ano_real_por_cnpj = dict(cursor.execute(
        f"""
        SELECT fundo_cnpj, MAX(ano_referencia) FROM demonstracoes
        WHERE tipo_demonstracao NOT IN ({placeholders_marcadores})
        GROUP BY fundo_cnpj
        """,
        MARCADORES_SINTETICOS,
    ))

    estado_por_cnpj = {}
    for cnpj, data_constituicao, exercicio_social_inicio in cursor.execute(
        "SELECT cnpj, data_constituicao, exercicio_social_inicio FROM fundos WHERE data_constituicao IS NOT NULL"
    ):
        ultimo_ano_real = ultimo_ano_real_por_cnpj.get(cnpj)
        if exercicio_social_inicio:
            resultado = _classificar_por_ciclo_exercicio(
                data_constituicao, exercicio_social_inicio, ultimo_ano_real, hoje
            )
        else:
            resultado = _classificar_por_janela_dias(data_constituicao, ultimo_ano_real, hoje)

        if resultado:
            estado_por_cnpj[cnpj] = resultado

    marcadores_atuais = {
        (row[0], row[1], row[2]) for row in cursor.execute(
            f"""
            SELECT fundo_cnpj, tipo_demonstracao, ano_referencia FROM demonstracoes
            WHERE tipo_demonstracao IN ({placeholders_marcadores})
            """,
            MARCADORES_SINTETICOS,
        )
    }
    marcadores_desejados = {
        (cnpj, tipo, ano_ref) for cnpj, (tipo, _, ano_ref) in estado_por_cnpj.items()
    }

    a_remover = marcadores_atuais - marcadores_desejados
    a_inserir = marcadores_desejados - marcadores_atuais

    if a_remover:
        cursor.executemany(
            "DELETE FROM demonstracoes WHERE fundo_cnpj = ? AND tipo_demonstracao = ? AND ano_referencia = ?",
            list(a_remover),
        )

    linhas = [
        (cnpj, ano_ref, tipo, estado_por_cnpj[cnpj][1])
        for cnpj, tipo, ano_ref in a_inserir
    ]
    if linhas:
        cursor.executemany(
            """
            INSERT INTO demonstracoes (fundo_cnpj, ano_referencia, tipo_demonstracao, opiniao_auditor)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (fundo_cnpj, ano_referencia, tipo_demonstracao) DO NOTHING
            """,
            linhas,
        )
    conn.commit()
    return len(linhas), len(a_remover)


def atualizar_demonstracoes():
    conn = obter_conexao()
    erros_anos = []
    try:
        cnpjs_validos = {linha[0] for linha in conn.execute("SELECT cnpj FROM fundos")}
        ano_atual = date.today().year
        # Ano atual pode ainda nao ter arquivo publicado (ex: inicio de janeiro) -
        # um ano falhar nao pode impedir o outro de ser processado.
        for ano in (ano_atual, ano_atual - 1):
            try:
                processar_ano(conn, ano, cnpjs_validos)
            except Exception as exc:
                erros_anos.append((ano, exc))

        inicio = time.monotonic()
        try:
            marcadas, removidas = sincronizar_situacao_df(conn)
            registrar_log(
                conn, NOME_PIPELINE, NOME_BASE_FUNDOS_NOVOS, "SUCESSO",
                competencia=str(ano_atual), linhas_processadas=marcadas,
                linhas_inseridas=marcadas, linhas_atualizadas=removidas,
                duracao_segundos=time.monotonic() - inicio,
            )
        except Exception as exc:
            registrar_log(
                conn, NOME_PIPELINE, NOME_BASE_FUNDOS_NOVOS, "ERRO",
                competencia=str(ano_atual), mensagem_erro=str(exc),
                duracao_segundos=time.monotonic() - inicio,
            )
            raise
    finally:
        conn.close()

    if len(erros_anos) == 2:
        raise erros_anos[-1][1]


if __name__ == "__main__":
    atualizar_demonstracoes()
