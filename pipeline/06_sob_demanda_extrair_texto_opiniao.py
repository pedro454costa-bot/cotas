"""Extracao do trecho de opiniao do auditor a partir do PDF da Demonstracao Financeira.

Fase "Extracao" do modulo de IA (ver CLAUDE.md): baixa o PDF (link ja vem pronto
em demonstracoes.arquivo_origem), extrai o texto localmente com pypdf, recorta as
secoes "Opiniao" e "Base para opiniao" do Relatorio dos Auditores Independentes
(ver pipeline/opiniao_secoes.py, que cobre tambem opiniao com ressalva, adversa e
abstencao de opiniao), mais as secoes de Enfase / Incerteza relevante / Outros
assuntos, e guarda so esses trechos em demonstracoes_extracao - a proxima fase
(prompt/LLM, ainda nao implementada) le daqui em vez de reprocessar o PDF inteiro,
com uma fracao do texto.

Nao chama nenhuma LLM. Sem custo de API - so download + parsing local.

Download+parse e I/O-bound (rede), entao roda em pool de threads (NUM_WORKERS_PADRAO)
- cada worker so baixa/parseia (sem tocar no banco); a persistencia no SQLite fica
so na thread principal, um resultado por vez, conforme vao terminando. Cada
documento e salvo assim que termina (nao espera o lote inteiro), e a cada um
tambem atualiza um arquivo de status (ver ARQUIVO_STATUS) - da pra acompanhar o
andamento com pipeline/status_extracao_opiniao.py enquanto roda.

Pula quem ja foi extraido (usa o cache em pipeline/raw/pdfs_demonstracoes/ e a
tabela demonstracoes_extracao) - seguro de rodar varias vezes / retomar do ponto
que parou.

Uso:
    python pipeline/06_sob_demanda_extrair_texto_opiniao.py                  # lote pequeno (20), prioriza quem nao tem opiniao da CVM
    python pipeline/06_sob_demanda_extrair_texto_opiniao.py 200              # lote de 200
    python pipeline/06_sob_demanda_extrair_texto_opiniao.py --todos          # sem limite (todos os pendentes)
    python pipeline/06_sob_demanda_extrair_texto_opiniao.py --apenas-sem-opiniao  # so quem a CVM nao informou opiniao
    python pipeline/06_sob_demanda_extrair_texto_opiniao.py --forcar 10      # reprocessa mesmo quem ja tem extracao salva
    python pipeline/06_sob_demanda_extrair_texto_opiniao.py --todos --workers 12  # paralelismo customizado
    python pipeline/06_sob_demanda_extrair_texto_opiniao.py --escopo-4655 --workers 8  # so o recorte do Excel (fundos_status_df_*.xlsx, "DF Real Encontrada"=Sim)
    python pipeline/06_sob_demanda_extrair_texto_opiniao.py --fontes-opiniao --workers 8  # base priorizada de fontes_opiniao_auditor (07_sob_demanda_montar_base_opiniao.py)
    python pipeline/06_sob_demanda_extrair_texto_opiniao.py --ultima-df --workers 8  # so a DF mais recente de cada fundo, TODO fundo que publicou (pula quem ja tem opiniao_estruturada ou PDF extraido)
    python pipeline/06_sob_demanda_extrair_texto_opiniao.py --ultima-df --so-cadastro-ativo  # idem, restrito aos fundos presentes na tabela `fundos`
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pypdf import PdfReader
from pypdf.errors import PdfReadError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from pipeline.opiniao_secoes import extrair_secoes
from pipeline.pdf_texto import extrair_texto
from pipeline.utils import ORDEM_PRIORIDADE_ORIGEM, obter_conexao, registrar_log

NOME_PIPELINE = "extrair_texto_opiniao"
NOME_BASE = "demonstracoes_extracao"

PDF_DIR = config.RAW_DIR / "pdfs_demonstracoes"
ARQUIVO_STATUS = config.RAW_DIR / "status_extracao_opiniao.json"

MARCADORES_SINTETICOS = ("NOVO", "DENTRO_DO_PRAZO", "ATRASO")

LIMITE_PADRAO = 20
NUM_WORKERS_PADRAO = 8  # download e I/O-bound - paralelizar aqui e o que mais acelera o lote
MIN_CHARS_TEXTO_VALIDO = 200  # abaixo disso, quase certo que o PDF e so imagem escaneada (sem camada de texto)

# O recorte em si (achar o titulo "Opiniao"/"Opiniao com ressalva"/"Abstencao de
# opiniao" e o "Base para ..." correspondente) fica em pipeline/opiniao_secoes.py.
# Aqui so entra o texto completo do PDF e saem as duas secoes ja enxutas.


def obter_candidatos_escopo_4655(conn, forcar):
    """Recorte especifico: fundos 'Em Funcionamento Normal' cujo exercicio mais
    recente ainda esta com marcador sintetico (Atraso/Dentro do Prazo) mas que
    JA TEM uma DF real de ano anterior arquivada ("DF Real Encontrada na Eventual"
    = Sim no export Excel) - so a DF real mais recente de cada um desses fundos
    (1 documento por fundo). E o mesmo recorte de fundos_status_df_*.xlsx."""
    condicao_forcar = "" if forcar else (
        "AND NOT EXISTS (SELECT 1 FROM demonstracoes_extracao e WHERE e.demonstracao_id = d.id)"
    )
    sql = f"""
        WITH marcados AS (
            SELECT DISTINCT d.fundo_cnpj
            FROM demonstracoes d
            JOIN fundos f ON f.cnpj = d.fundo_cnpj
            WHERE f.situacao = 'Em Funcionamento Normal'
            AND d.tipo_demonstracao IN ('ATRASO', 'DENTRO_DO_PRAZO')
        ),
        reais_recentes AS (
            SELECT d.id, d.fundo_cnpj,
                   ROW_NUMBER() OVER (PARTITION BY d.fundo_cnpj ORDER BY d.ano_referencia DESC) AS posicao
            FROM demonstracoes d
            WHERE d.tipo_demonstracao NOT IN ({', '.join('?' for _ in MARCADORES_SINTETICOS)})
            AND d.fundo_cnpj IN (SELECT fundo_cnpj FROM marcados)
        )
        SELECT d.id, d.fundo_cnpj, d.ano_referencia, d.tipo_demonstracao, d.arquivo_origem
        FROM demonstracoes d
        JOIN reais_recentes r ON r.id = d.id
        WHERE r.posicao = 1
        AND d.arquivo_origem IS NOT NULL AND d.arquivo_origem != ''
        {condicao_forcar}
        ORDER BY d.opiniao_auditor IS NOT NULL, d.ano_referencia DESC
    """
    return conn.execute(sql, list(MARCADORES_SINTETICOS)).fetchall()


def obter_candidatos(conn, limite, apenas_sem_opiniao, forcar):
    condicoes = [
        "f.situacao IN ('Em Funcionamento Normal', 'Fase Pré-Operacional')",
        f"d.tipo_demonstracao NOT IN ({', '.join('?' for _ in MARCADORES_SINTETICOS)})",
        "d.arquivo_origem IS NOT NULL AND d.arquivo_origem != ''",
    ]
    parametros = list(MARCADORES_SINTETICOS)

    if apenas_sem_opiniao:
        condicoes.append("d.opiniao_auditor IS NULL")
    if not forcar:
        condicoes.append("NOT EXISTS (SELECT 1 FROM demonstracoes_extracao e WHERE e.demonstracao_id = d.id)")

    sql = f"""
        SELECT d.id, d.fundo_cnpj, d.ano_referencia, d.tipo_demonstracao, d.arquivo_origem
        FROM demonstracoes d
        JOIN fundos f ON f.cnpj = d.fundo_cnpj
        WHERE {' AND '.join(condicoes)}
        ORDER BY d.opiniao_auditor IS NOT NULL, d.ano_referencia DESC
    """
    if limite is not None:
        sql += " LIMIT ?"
        parametros.append(limite)

    return conn.execute(sql, parametros).fetchall()


def _sql_prioridade_origem():
    casos = " ".join(f"WHEN '{origem}' THEN {prioridade}" for origem, prioridade in ORDEM_PRIORIDADE_ORIGEM.items())
    return f"CASE origem {casos} ELSE 99 END"


def obter_candidatos_fontes_opiniao(conn, forcar):
    """Base montada por 07_sob_demanda_montar_base_opiniao.py (fontes_opiniao_auditor) -
    junta EVENTUAL (PARECER AUD./DF/DF ANUAL FII/FIAGRO), DFIN_FII e arquivo manual.
    Quando um fundo/ano tem mais de uma origem disponivel, pega so a de maior
    prioridade (ver ORDEM_PRIORIDADE_ORIGEM em pipeline/utils.py) - normalmente o
    documento mais direto (PARECER AUD./DFIN), evitando abrir a DF inteira a toa."""
    condicao_forcar = "" if forcar else (
        "AND NOT EXISTS (SELECT 1 FROM fontes_opiniao_extracao e WHERE e.fonte_opiniao_id = p.id)"
    )
    sql = f"""
        WITH priorizadas AS (
            SELECT f.id, f.fundo_cnpj, f.ano_referencia, f.origem, f.link_arquivo,
                   ROW_NUMBER() OVER (
                       PARTITION BY f.fundo_cnpj, f.ano_referencia
                       ORDER BY {_sql_prioridade_origem()}
                   ) AS posicao
            FROM fontes_opiniao_auditor f
            WHERE f.fundo_cnpj IS NOT NULL AND f.ano_referencia IS NOT NULL
            AND f.link_arquivo IS NOT NULL AND f.link_arquivo != ''
        )
        SELECT p.id, p.fundo_cnpj, p.ano_referencia, p.origem, p.link_arquivo
        FROM priorizadas p
        WHERE p.posicao = 1
        {condicao_forcar}
    """
    return conn.execute(sql).fetchall()


def obter_candidatos_ultima_df(conn, forcar, apenas_cadastro_ativo=False):
    """So a DF MAIS RECENTE de cada fundo (nao 1 linha por fundo/ano) - objetivo e
    sempre a demonstracao mais atual, entao processar anos antigos de um fundo que
    ja tem ano mais novo disponivel e trabalho desperdicado.

    Por padrao NAO filtra por cadastro: o universo e "todo fundo que publicou DF ou
    parecer", venha ele do eventual, do DFIN ou do arquivo manual. Fundo cancelado,
    liquidado ou incorporado publica DF e e justamente o que a area de Risco precisa
    ler - amarrar a extracao a tabela `fundos` escondia ~11 mil fundos, porque
    01_diario_update_registro_fundo.py so grava situacao ativa e administrador nao
    excluido (config.SITUACOES_FUNDO_VALIDAS / ADMINISTRADORES_EXCLUIDOS_*), entao
    o filtro acabava aplicado duas vezes sem aparecer.

    apenas_cadastro_ativo=True (flag --so-cadastro-ativo) restaura o comportamento
    antigo, restrito aos fundos presentes no cadastro.

    Em ambos os casos pula quem ja tem opiniao_estruturada pronta
    (DFIN_FII/ARQUIVO_MANUAL_OPINIAO_PRONTA ja veio classificada pela CVM, nao
    precisa abrir PDF)."""
    condicao_forcar = "" if forcar else (
        "AND NOT EXISTS (SELECT 1 FROM fontes_opiniao_extracao e WHERE e.fonte_opiniao_id = u.id)"
    )
    juncao_cadastro = "JOIN fundos fu ON fu.cnpj = f.fundo_cnpj" if apenas_cadastro_ativo else ""
    sql = f"""
        WITH
        -- opiniao_estruturada NAO filtra aqui de proposito: precisa entrar na
        -- disputa por "ano mais recente do fundo" antes de decidir se sobra
        -- trabalho de extracao de PDF. Filtrar cedo demais faria o fundo cair
        -- pro ano anterior quando o mais recente ja veio classificado pela CVM.
        fontes_validas AS (
            SELECT f.id, f.fundo_cnpj, f.ano_referencia, f.origem, f.link_arquivo, f.opiniao_estruturada
            FROM fontes_opiniao_auditor f
            {juncao_cadastro}
            WHERE f.fundo_cnpj IS NOT NULL AND f.ano_referencia IS NOT NULL
            AND f.link_arquivo IS NOT NULL AND f.link_arquivo != ''
        ),
        melhor_por_ano AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY fundo_cnpj, ano_referencia ORDER BY {_sql_prioridade_origem()}
            ) AS posicao_origem
            FROM fontes_validas
        ),
        ultima_por_fundo AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY fundo_cnpj ORDER BY ano_referencia DESC
            ) AS posicao_ano
            FROM melhor_por_ano
            WHERE posicao_origem = 1
        )
        SELECT u.id, u.fundo_cnpj, u.ano_referencia, u.origem, u.link_arquivo
        FROM ultima_por_fundo u
        WHERE posicao_ano = 1
        AND u.opiniao_estruturada IS NULL
        {condicao_forcar}
    """
    return conn.execute(sql).fetchall()


COLUNAS_RECORTE = (
    "trecho_enfase_outros", "secoes_adicionais",
    "titulo_opiniao", "titulo_base", "tipo_opiniao_detectado", "metodo_recorte",
)


def garantir_colunas_recorte(conn):
    """Cria as colunas do recorte em bancos criados antes delas existirem.

    db/criar_banco.py ja as declara, mas o banco em producao nao e recriado a cada
    versao - sem isso o INSERT quebraria em base antiga."""
    for tabela in ("demonstracoes_extracao", "fontes_opiniao_extracao"):
        existentes = {linha[1] for linha in conn.execute(f"PRAGMA table_info({tabela})")}
        if not existentes:
            continue
        for coluna in COLUNAS_RECORTE:
            if coluna not in existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} TEXT")
    conn.commit()


def caminho_pdf_cache(fundo_cnpj, ano_referencia, tipo_demonstracao):
    tipo_arquivo = re.sub(r"[^A-Za-z0-9]+", "_", tipo_demonstracao).strip("_")
    return PDF_DIR / f"{fundo_cnpj}_{ano_referencia}_{tipo_arquivo}.pdf"


def criar_sessao_com_retry():
    """Cria sessao requests com retry automático para timeouts e erros temporários."""
    sessao = requests.Session()
    retry_strategy = Retry(
        total=4,  # aumentado de 3 para 4
        backoff_factor=1.5,  # 1.5s, 2.25s, 3.4s, 5.1s
        status_forcelist=[403, 408, 429, 500, 502, 503, 504],  # adicionado 403
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    sessao.mount("http://", adapter)
    sessao.mount("https://", adapter)

    # Headers que fazem parecer um navegador real (evita 403)
    sessao.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return sessao


def baixar_pdf(sessao, url, destino):
    """Baixa PDF com retry automático. Timeout de 90s (mais tolerante para fnet lento)."""
    if destino.exists() and destino.stat().st_size > 0:
        return
    destino.parent.mkdir(parents=True, exist_ok=True)

    # Pequeno delay para não parecer bot (headers já ajustados na sessão)
    time.sleep(0.2)

    resposta = sessao.get(
        url,
        timeout=90,  # aumentado de 60 para 90 (fnet costuma ser lento)
        allow_redirects=True
    )
    resposta.raise_for_status()
    destino.write_bytes(resposta.content)


def extrair_texto_pdf(caminho):
    """Texto do PDF pelo extrator com reparo de fonte (ver pipeline/pdf_texto.py).

    O pypdf puro devolvia lixo em PDF com ToUnicode quebrado - o documento parecia
    escaneado quando na verdade era so o mapa de glifos errado."""
    resultado = extrair_texto(str(caminho))
    return resultado.texto, resultado.paginas


def processar_documento(linha, sessao):
    demonstracao_id, fundo_cnpj, ano_referencia, tipo_demonstracao, url = linha
    destino = caminho_pdf_cache(fundo_cnpj, ano_referencia, tipo_demonstracao)

    resultado = {
        "demonstracao_id": demonstracao_id,
        "caminho_pdf": str(destino),
        "numero_paginas": None,
        "tamanho_pdf_bytes": None,
        "encontrou_secao_opiniao": 0,
        "trecho_opiniao": None,
        "trecho_opiniao_secao": None,
        "trecho_base_opiniao": None,
        "trecho_enfase_outros": None,
        "secoes_adicionais": None,
        "titulo_opiniao": None,
        "titulo_base": None,
        "tipo_opiniao_detectado": None,
        "metodo_recorte": None,
        "metodo_extracao": None,
        "mensagem_erro": None,
    }

    try:
        baixar_pdf(sessao, url, destino)
        resultado["tamanho_pdf_bytes"] = destino.stat().st_size

        texto, num_paginas = extrair_texto_pdf(destino)
        resultado["numero_paginas"] = num_paginas

        if len(texto.strip()) < MIN_CHARS_TEXTO_VALIDO:
            resultado["metodo_extracao"] = "sem_texto_possivel_scan"
            return resultado

        secoes = extrair_secoes(texto)
        resultado["metodo_recorte"] = secoes.metodo_recorte
        if secoes.trecho_opiniao_secao:
            resultado["encontrou_secao_opiniao"] = 1
            resultado["trecho_opiniao_secao"] = secoes.trecho_opiniao_secao
            resultado["trecho_base_opiniao"] = secoes.trecho_base_opiniao
            resultado["trecho_enfase_outros"] = secoes.trecho_enfase_outros
            resultado["secoes_adicionais"] = secoes.secoes_adicionais
            resultado["titulo_opiniao"] = secoes.titulo_opiniao
            resultado["titulo_base"] = secoes.titulo_base
            resultado["tipo_opiniao_detectado"] = secoes.tipo_opiniao_detectado
            # trecho_opiniao (coluna antiga) = o pacote completo que vai para a LLM:
            # as duas secoes ja recortadas, na ordem em que aparecem no relatorio.
            resultado["trecho_opiniao"] = "\n\n".join(
                parte for parte in (secoes.trecho_opiniao_secao, secoes.trecho_base_opiniao,
                                    secoes.trecho_enfase_outros) if parte
            )
            resultado["metodo_extracao"] = "secoes_recortadas"
        else:
            resultado["metodo_extracao"] = "texto_ok_titulo_opiniao_nao_localizado"

    except (requests.RequestException, PdfReadError, OSError, Exception) as exc:
        # Captura ampla de proposito: um PDF individual corrompido/criptografado/
        # atipico nao pode derrubar o lote inteiro - fica marcado como erro e o
        # resto do lote continua.
        resultado["metodo_extracao"] = "erro"
        resultado["mensagem_erro"] = f"{type(exc).__name__}: {exc}"[:500]

    return resultado


def persistir(conn, resultado):
    conn.execute(
        """
        INSERT INTO demonstracoes_extracao
            (demonstracao_id, caminho_pdf, numero_paginas, tamanho_pdf_bytes,
             encontrou_secao_opiniao, trecho_opiniao, trecho_opiniao_secao, trecho_base_opiniao,
             trecho_enfase_outros, secoes_adicionais, titulo_opiniao, titulo_base, tipo_opiniao_detectado, metodo_recorte,
             metodo_extracao, mensagem_erro)
        VALUES (:demonstracao_id, :caminho_pdf, :numero_paginas, :tamanho_pdf_bytes,
                :encontrou_secao_opiniao, :trecho_opiniao, :trecho_opiniao_secao, :trecho_base_opiniao,
                :trecho_enfase_outros, :secoes_adicionais, :titulo_opiniao, :titulo_base, :tipo_opiniao_detectado, :metodo_recorte,
                :metodo_extracao, :mensagem_erro)
        ON CONFLICT (demonstracao_id) DO UPDATE SET
            caminho_pdf = excluded.caminho_pdf,
            numero_paginas = excluded.numero_paginas,
            tamanho_pdf_bytes = excluded.tamanho_pdf_bytes,
            encontrou_secao_opiniao = excluded.encontrou_secao_opiniao,
            trecho_opiniao = excluded.trecho_opiniao,
            trecho_opiniao_secao = excluded.trecho_opiniao_secao,
            trecho_base_opiniao = excluded.trecho_base_opiniao,
            trecho_enfase_outros = excluded.trecho_enfase_outros,
            secoes_adicionais = excluded.secoes_adicionais,
            titulo_opiniao = excluded.titulo_opiniao,
            titulo_base = excluded.titulo_base,
            tipo_opiniao_detectado = excluded.tipo_opiniao_detectado,
            metodo_recorte = excluded.metodo_recorte,
            metodo_extracao = excluded.metodo_extracao,
            mensagem_erro = excluded.mensagem_erro,
            atualizado_em = datetime('now', 'localtime')
        """,
        resultado,
    )
    conn.commit()


def persistir_fonte_opiniao(conn, resultado):
    """Mesma coisa que persistir(), mas pra fontes_opiniao_extracao (fonte_opiniao_id
    em vez de demonstracao_id) - usado quando o lote vem de obter_candidatos_fontes_opiniao."""
    corpo = dict(resultado)
    corpo["fonte_opiniao_id"] = corpo.pop("demonstracao_id")
    conn.execute(
        """
        INSERT INTO fontes_opiniao_extracao
            (fonte_opiniao_id, caminho_pdf, numero_paginas, tamanho_pdf_bytes,
             encontrou_secao_opiniao, trecho_opiniao, trecho_opiniao_secao, trecho_base_opiniao,
             trecho_enfase_outros, secoes_adicionais, titulo_opiniao, titulo_base, tipo_opiniao_detectado, metodo_recorte,
             metodo_extracao, mensagem_erro)
        VALUES (:fonte_opiniao_id, :caminho_pdf, :numero_paginas, :tamanho_pdf_bytes,
                :encontrou_secao_opiniao, :trecho_opiniao, :trecho_opiniao_secao, :trecho_base_opiniao,
                :trecho_enfase_outros, :secoes_adicionais, :titulo_opiniao, :titulo_base, :tipo_opiniao_detectado, :metodo_recorte,
                :metodo_extracao, :mensagem_erro)
        ON CONFLICT (fonte_opiniao_id) DO UPDATE SET
            caminho_pdf = excluded.caminho_pdf,
            numero_paginas = excluded.numero_paginas,
            tamanho_pdf_bytes = excluded.tamanho_pdf_bytes,
            encontrou_secao_opiniao = excluded.encontrou_secao_opiniao,
            trecho_opiniao = excluded.trecho_opiniao,
            trecho_opiniao_secao = excluded.trecho_opiniao_secao,
            trecho_base_opiniao = excluded.trecho_base_opiniao,
            trecho_enfase_outros = excluded.trecho_enfase_outros,
            secoes_adicionais = excluded.secoes_adicionais,
            titulo_opiniao = excluded.titulo_opiniao,
            titulo_base = excluded.titulo_base,
            tipo_opiniao_detectado = excluded.tipo_opiniao_detectado,
            metodo_recorte = excluded.metodo_recorte,
            metodo_extracao = excluded.metodo_extracao,
            mensagem_erro = excluded.mensagem_erro,
            atualizado_em = datetime('now', 'localtime')
        """,
        corpo,
    )
    conn.commit()


def escrever_status(iniciado_em, alvo_total, processados, contagem_metodo, concluido=False):
    agora = time.monotonic()
    decorrido = agora - escrever_status._t0
    taxa_por_min = processados / (decorrido / 60) if decorrido > 0 else 0
    restantes = alvo_total - processados
    eta_minutos = (restantes / taxa_por_min) if taxa_por_min > 0 else None

    corpo = {
        "iniciado_em": iniciado_em,
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "concluido": concluido,
        "alvo_total": alvo_total,
        "processados": processados,
        "percentual": round(processados / alvo_total * 100, 1) if alvo_total else None,
        "taxa_por_minuto": round(taxa_por_min, 1),
        "eta_minutos": round(eta_minutos, 1) if eta_minutos is not None else None,
        "contagem_metodo": contagem_metodo,
    }
    # E so um relatorio de progresso pra acompanhar de fora - nunca pode derrubar o
    # lote inteiro. No Windows, o rename pra ARQUIVO_STATUS pode falhar com "acesso
    # negado"/"em uso" se outro processo (ex: status_extracao_opiniao.py) estiver
    # lendo o arquivo bem nesse instante - so tenta de novo na proxima atualizacao.
    try:
        ARQUIVO_STATUS.parent.mkdir(parents=True, exist_ok=True)
        # Escreve em arquivo temporario e renomeia - evita status.py ler um JSON
        # pela metade enquanto esse processo esta escrevendo.
        temporario = ARQUIVO_STATUS.with_suffix(".tmp")
        temporario.write_text(json.dumps(corpo, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(ARQUIVO_STATUS)
    except OSError:
        pass


def extrair_lote(limite=LIMITE_PADRAO, apenas_sem_opiniao=False, forcar=False, workers=NUM_WORKERS_PADRAO,
                  escopo_4655=False, fontes_opiniao=False, ultima_df=False,
                  so_cadastro_ativo=False):
    inicio = time.monotonic()
    escrever_status._t0 = inicio
    iniciado_em = datetime.now().isoformat(timespec="seconds")

    PDF_DIR.mkdir(parents=True, exist_ok=True)

    conn = obter_conexao()
    garantir_colunas_recorte(conn)
    contagem_metodo = {}
    processados = 0
    sessao = criar_sessao_com_retry()  # Cria sessão reutilizável com retry
    nome_base_log = NOME_BASE
    funcao_persistir = persistir
    try:
        if ultima_df:
            candidatos = obter_candidatos_ultima_df(conn, forcar, apenas_cadastro_ativo=so_cadastro_ativo)
            nome_base_log = "fontes_opiniao_extracao"
            funcao_persistir = persistir_fonte_opiniao
        elif fontes_opiniao:
            candidatos = obter_candidatos_fontes_opiniao(conn, forcar)
            nome_base_log = "fontes_opiniao_extracao"
            funcao_persistir = persistir_fonte_opiniao
        elif escopo_4655:
            candidatos = obter_candidatos_escopo_4655(conn, forcar)
        else:
            candidatos = obter_candidatos(conn, limite, apenas_sem_opiniao, forcar)
        alvo_total = len(candidatos)
        print(f"Candidatos a processar: {alvo_total} (workers={workers}, fonte={('fontes_opiniao_auditor (ultima DF por fundo' + (', so cadastro ativo)' if so_cadastro_ativo else ', todo fundo que publicou)')) if ultima_df else 'fontes_opiniao_auditor' if fontes_opiniao else 'demonstracoes'})")
        escrever_status(iniciado_em, alvo_total, 0, contagem_metodo)

        # Wrapper para passar sessão aos workers
        def processar_com_sessao(linha):
            return processar_documento(linha, sessao)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futuros = {executor.submit(processar_com_sessao, linha): linha for linha in candidatos}
            for futuro in as_completed(futuros):
                linha = futuros[futuro]
                resultado = futuro.result()
                funcao_persistir(conn, resultado)
                processados += 1
                contagem_metodo[resultado["metodo_extracao"]] = contagem_metodo.get(resultado["metodo_extracao"], 0) + 1
                escrever_status(iniciado_em, alvo_total, processados, contagem_metodo)
                print(f"  [{processados}/{alvo_total}] id={linha[0]} origem/tipo={linha[3]} -> {resultado['metodo_extracao']}")

        escrever_status(iniciado_em, alvo_total, processados, contagem_metodo, concluido=True)
        registrar_log(
            conn, NOME_PIPELINE, nome_base_log, "SUCESSO",
            linhas_processadas=processados, linhas_inseridas=processados,
            duracao_segundos=time.monotonic() - inicio,
        )
    except Exception as exc:
        registrar_log(
            conn, NOME_PIPELINE, nome_base_log, "ERRO",
            mensagem_erro=str(exc), duracao_segundos=time.monotonic() - inicio,
        )
        raise
    finally:
        sessao.close()
        conn.close()

    print(f"\nResumo por metodo_extracao: {contagem_metodo}")
    return contagem_metodo


if __name__ == "__main__":
    _limite = LIMITE_PADRAO
    _apenas_sem_opiniao = False
    _forcar = False
    _workers = NUM_WORKERS_PADRAO
    _escopo_4655 = False
    _fontes_opiniao = False
    _ultima_df = False
    _so_cadastro_ativo = False
    _argv = sys.argv[1:]
    _i = 0
    while _i < len(_argv):
        _arg = _argv[_i]
        if _arg == "--todos":
            _limite = None
        elif _arg == "--apenas-sem-opiniao":
            _apenas_sem_opiniao = True
        elif _arg == "--forcar":
            _forcar = True
        elif _arg == "--escopo-4655":
            _escopo_4655 = True
            _limite = None
        elif _arg == "--fontes-opiniao":
            _fontes_opiniao = True
            _limite = None
        elif _arg == "--ultima-df":
            _ultima_df = True
        elif _arg == "--so-cadastro-ativo":
            _so_cadastro_ativo = True
            _limite = None
        elif _arg == "--workers" and _i + 1 < len(_argv):
            _workers = int(_argv[_i + 1])
            _i += 1  # pula o valor, senao o loop reprocessa como se fosse o limite
        elif _arg.isdigit():
            _limite = int(_arg)
        _i += 1

    extrair_lote(limite=_limite, apenas_sem_opiniao=_apenas_sem_opiniao, forcar=_forcar, workers=_workers,
                 escopo_4655=_escopo_4655, fontes_opiniao=_fontes_opiniao, ultima_df=_ultima_df,
                 so_cadastro_ativo=_so_cadastro_ativo)
