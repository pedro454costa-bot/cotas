"""Tela 'Analise Rapida de Fundo' - busca por CNPJ, grafo de risco e painel lateral.

Tudo em funcoes (sem classes). Cada funcao de consulta abre e fecha sua propria
conexao sqlite3 - simples de ler, sem camada de Repository/Service.
"""

import base64
import math
import sqlite3
import sys
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import networkx as nx
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from streamlit_agraph import Config, Edge, Node, agraph

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.utils import normalizar_cnpj, obter_conexao

CHAVE_FUNDO_SELECIONADO = "fundo_selecionado_cnpj"

BORDO = "#6B0F26"
BORDO_ESCURO = "#4A0A1B"

RISCO_BAIXO = "#1BA84A"
RISCO_MEDIO = "#D4A017"
RISCO_ALTO = "#DC2626"
RISCO_SEM_DADO = "#9CA3AF"

CORES_RISCO = {"ALTO": RISCO_ALTO, "MEDIO": RISCO_MEDIO, "BAIXO": RISCO_BAIXO, None: RISCO_SEM_DADO}
CORES_RISCO_CLARO = {
    "ALTO": "#FDECEC", "MEDIO": "#FCF3DA", "BAIXO": "#E4F6EA", None: "#F1F0EF",
}
LABELS_RISCO = {
    "ALTO": "Risco Alto", "MEDIO": "Risco Medio", "BAIXO": "Risco Baixo", None: "Sem classificacao",
}
BADGE_CSS_CLASSE = {"ALTO": "rm-badge-alto", "MEDIO": "rm-badge-medio", "BAIXO": "rm-badge-baixo"}

CODIGO_OPINIAO_NOVO = "NOVO"
CODIGO_OPINIAO_DENTRO_DO_PRAZO = "DENTRO_DO_PRAZO"
CODIGO_OPINIAO_ATRASO = "ATRASO"

# Fundo sem nenhuma DF real - estado sintetico calculado pelo pipeline (ver
# DIAS_JANELA_FUNDO_NOVO/DIAS_LIMITE_ATRASO em update_demonstracoes) a partir do
# tempo desde a constituicao. (rotulo, classe css do badge)
SITUACAO_DF_SINTETICA = {
    CODIGO_OPINIAO_NOVO: ("Novo", "rm-badge-semdado"),
    CODIGO_OPINIAO_DENTRO_DO_PRAZO: ("Dentro do Prazo", "rm-badge-baixo"),
    CODIGO_OPINIAO_ATRASO: ("Em Atraso", "rm-badge-alto"),
}

OPINIAO_LABELS = {
    "SEM_RESSALVA": "Sem Ressalva", "RESSALVA": "Ressalva", "ADVERSA": "Opiniao Adversa",
    "ABSTENCAO": "Abstencao de Opiniao", "DISPENSADO": "Dispensado", "OUTRO": "Outro",
}
OPINIAO_BADGE_CLASSE = {
    "SEM_RESSALVA": "rm-badge-baixo", "DISPENSADO": "rm-badge-baixo", "RESSALVA": "rm-badge-medio",
    "ADVERSA": "rm-badge-alto", "ABSTENCAO": "rm-badge-alto", "OUTRO": "rm-badge-semdado",
}
# Opinioes modificadas - unicas onde faz sentido mostrar descricao/potencial risco (vem da IA).
OPINIOES_COM_RESSALVA = {"RESSALVA", "ADVERSA", "ABSTENCAO"}

TIPO_DEMONSTRACAO_LABELS = {
    "DEMONST CONTAB": "Demonstracao Contabil", "DF": "Demonstracao Financeira",
    "DF ANUAL FIAGRO": "DF Anual FIAGRO", "DF ANUAL FII": "DF Anual FII",
}

CSS = f"""
<style>
:root {{ --rm-bordo: {BORDO}; --rm-bordo-escuro: {BORDO_ESCURO}; }}
.stApp {{ background: #F7F6F5; }}
section.main > div.block-container {{ padding-top: 1rem; max-width: 100%; }}
[data-testid="stSidebar"] {{ display: none; }}
h1, h2, h3 {{ color: #1f1b18; }}
.stButton>button {{ background: var(--rm-bordo); color: #fff; border: 1px solid var(--rm-bordo); border-radius: 8px; font-weight: 600; }}
.stButton>button:hover {{ background: var(--rm-bordo-escuro); border-color: var(--rm-bordo-escuro); color: #fff; }}
.stTextInput input:focus {{ border-color: var(--rm-bordo) !important; box-shadow: 0 0 0 1px var(--rm-bordo) !important; }}

.rm-topbar {{ display:flex; align-items:center; padding: 10px 4px 14px 4px; border-bottom: 1px solid #E5E1DE; margin-bottom: 10px; }}
.rm-brand {{ display:flex; align-items:center; gap:10px; }}
.rm-brand-icon {{ width:36px; height:36px; border-radius:8px; background: var(--rm-bordo); color:#fff; display:flex; align-items:center; justify-content:center; font-size:18px; font-weight:700; }}
.rm-brand-title {{ font-weight:700; font-size:1rem; color:#1f1b18; line-height:1.1; }}
.rm-brand-sub {{ font-size:.66rem; color:#8A8378; letter-spacing:.05em; }}
.rm-nav {{ display:flex; gap:22px; margin-left: 24px; }}
.rm-nav-item {{ font-size:.86rem; font-weight:600; color:#6B6560; padding-bottom:12px; }}
.rm-nav-item-ativo {{ color: var(--rm-bordo); border-bottom: 2px solid var(--rm-bordo); }}
.rm-nav-item-desabilitado {{ color:#c9c4c0; }}

.rm-empty {{ display:flex; flex-direction:column; align-items:center; justify-content:center; padding: 90px 20px; color:#8A8378; text-align:center; }}
.rm-empty-icon {{ font-size:2.2rem; margin-bottom:14px; opacity:.5; }}

.rm-alert-alto {{ display:flex; align-items:center; gap:12px; background:#FDECEC; border:1px solid #F5B5B5; border-radius:10px; padding:10px 14px; margin-bottom:12px; }}
.rm-alert-pill {{ background: {RISCO_ALTO}; color:#fff; font-size:.7rem; font-weight:700; padding:4px 10px; border-radius:999px; white-space:nowrap; }}
.rm-alert-texto {{ font-size:.84rem; color:#7a1f1f; }}

.rm-badge {{ display:inline-flex; align-items:center; gap:6px; padding:4px 12px; border-radius:999px; font-size:.78rem; font-weight:700; }}
.rm-badge i {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}
.rm-badge-alto {{ background:#FDECEC; color:{RISCO_ALTO}; }} .rm-badge-alto i {{ background:{RISCO_ALTO}; }}
.rm-badge-medio {{ background:#FCF3DA; color:#8a6a0a; }} .rm-badge-medio i {{ background:{RISCO_MEDIO}; }}
.rm-badge-baixo {{ background:#E4F6EA; color:{RISCO_BAIXO}; }} .rm-badge-baixo i {{ background:{RISCO_BAIXO}; }}
.rm-badge-semdado {{ background:#F1F0EF; color:#6B6560; }} .rm-badge-semdado i {{ background:{RISCO_SEM_DADO}; }}

.rm-panel-cnpj {{ font-size:.78rem; color:#8A8378; }}
.rm-panel-nome {{ font-size:1.05rem; font-weight:700; color:#1f1b18; line-height:1.3; margin: 2px 0; }}
.rm-panel-tipo {{ font-size:.8rem; color:#6B6560; margin-bottom:8px; }}
.rm-section-label {{ font-size:.68rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:#8A8378; margin: 16px 0 8px 0; }}
.rm-field-row {{ display:flex; align-items:baseline; justify-content:space-between; gap:12px; padding:7px 0; border-bottom:1px solid #F0EEEC; }}
.rm-field-row:last-child {{ border-bottom:none; }}
.rm-field-label {{ font-size:.78rem; color:#8A8378; white-space:nowrap; }}
.rm-field-value {{ font-size:.82rem; color:#2b2724; font-weight:600; text-align:right; }}

.rm-hist-card {{ background:#fff; border:1px solid #E5E1DE; border-left:3px solid var(--rm-bordo); border-radius:8px; padding:8px 12px; margin-bottom:8px; }}
.rm-hist-nome {{ font-size:.84rem; font-weight:700; color:#1f1b18; }}
.rm-hist-tipo {{ font-size:.72rem; color:#8A8378; display:flex; align-items:center; gap:6px; }}
.rm-hist-periodo {{ font-size:.74rem; color:#6B6560; margin-top:4px; display:flex; align-items:center; gap:6px; }}
.rm-pill-anterior {{ background:#FDECEC; color:{RISCO_ALTO}; font-size:.66rem; font-weight:700; padding:2px 8px; border-radius:999px; }}

[data-testid="stVerticalBlockBorderWrapper"] {{ border-color:#E5E1DE !important; border-radius:10px !important; }}
div:has(> [data-testid="stVerticalBlockBorderWrapper"]) {{ margin-bottom:12px; }}
.rm-section-label:first-child {{ margin-top:0; }}

.rm-df-card {{ background:#fff; border:1px solid #E5E1DE; border-radius:8px; padding:10px 12px; margin-bottom:8px; }}
.rm-df-card:last-child {{ margin-bottom:0; }}
.rm-df-header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; gap:10px; }}
.rm-df-titulo {{ font-size:.86rem; font-weight:700; color:#1f1b18; }}
.rm-df-desc-label {{ font-size:.68rem; font-weight:700; letter-spacing:.04em; color:#8A8378; margin-top:6px; }}
.rm-df-desc-texto {{ font-size:.82rem; color:#3a3530; margin: 4px 0 2px 0; }}
.rm-df-risco-box {{ background:#FDECEC; border:1px solid #F5B5B5; border-radius:8px; padding:10px 12px; margin-top:10px; }}
.rm-df-risco-titulo {{ font-size:.78rem; font-weight:700; color:#7a1f1f; margin-bottom:2px; }}
.rm-df-risco-texto {{ font-size:.8rem; color:#7a1f1f; }}

.rm-graph-hint {{ font-size:.72rem; color:#8A8378; text-align:right; margin-bottom:4px; }}
.rm-graph-stats {{ font-size:.82rem; color:#6B6560; text-align:right; margin-bottom:6px; }}
.rm-graph-stats b {{ color: var(--rm-bordo); }}
.rm-invest-diretos {{ display:flex; align-items:center; justify-content:flex-end; gap:8px; margin-bottom:6px; font-size:.78rem; color:#6B6560; flex-wrap:wrap; }}
.rm-legenda {{ display:flex; gap:16px; margin-top:8px; flex-wrap:wrap; }}
.rm-legenda-item {{ display:flex; align-items:center; gap:6px; font-size:.74rem; color:#6B6560; }}
.rm-legenda-item i {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
</style>
"""

LARGURA_MIN = 1.0
LARGURA_MAX = 8.0


# --------------------------------------------------------------------------- #
# Consultas ao banco (cada funcao abre/fecha sua propria conexao)
# --------------------------------------------------------------------------- #

def buscar_fundo_por_cnpj(cnpj):
    conn = obter_conexao()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM fundos WHERE cnpj = ?", (cnpj,)).fetchone()
    conn.close()
    return row


def obter_historico_prestadores(cnpj):
    """So o prestador imediatamente anterior ao atual, por tipo_prestador - o
    atual ja aparece em "Prestadores de Servico" (colunas de `fundos`)."""
    conn = obter_conexao()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT tipo_prestador, nome, data_inicio, data_fim
        FROM (
            SELECT tipo_prestador, nome, data_inicio, data_fim,
                   ROW_NUMBER() OVER (
                       PARTITION BY tipo_prestador ORDER BY data_inicio DESC
                   ) AS posicao
            FROM prestadores_historico
            WHERE fundo_cnpj = ?
        )
        WHERE posicao = 2
        ORDER BY tipo_prestador
        """,
        (cnpj,),
    ).fetchall()
    conn.close()
    return rows


def obter_demonstracoes_todas(cnpj):
    """Todo o historico de demonstracoes do fundo (real ou marcador sintetico),
    da mais recente pra mais antiga."""
    conn = obter_conexao()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT d.ano_referencia, d.tipo_demonstracao, d.opiniao_auditor, d.status,
               a.descricao_opiniao_modificada, a.potencial_risco_investidor
        FROM demonstracoes d
        LEFT JOIN demonstracoes_ai a ON a.demonstracao_id = d.id
        WHERE d.fundo_cnpj = ?
        ORDER BY d.ano_referencia DESC, d.tipo_demonstracao ASC
        """,
        (cnpj,),
    ).fetchall()
    conn.close()
    return rows


def obter_exemplos_cnpj(limite=3):
    conn = obter_conexao()
    rows = conn.execute("SELECT cnpj FROM fundos LIMIT ?", (limite,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def construir_subgrafo(cnpj_raiz, profundidade=1, max_nos=80):
    """BFS por cda_edges a partir do fundo raiz, usando NetworkX para montar/podar.

    profundidade=1 por padrao (so investimentos diretos) - com 2+ saltos o grafo
    fica denso demais pra qualquer layout ficar legivel quando o fundo tem varias
    dezenas de posicoes. Pra ver mais fundo, clica num no filho (recentraliza o
    grafo nele - ver renderizar_grafo).

    Retorna (nos, arestas) como listas de dicts simples.
    """
    conn = obter_conexao()
    conn.row_factory = sqlite3.Row

    raiz = conn.execute(
        "SELECT id, identificador FROM cda_nodes WHERE identificador = ? AND tipo_no = 'FUNDO'",
        (cnpj_raiz,),
    ).fetchone()
    if raiz is None:
        conn.close()
        return [], []

    grafo = nx.DiGraph()
    grafo.add_node(raiz["id"])
    visitados = {raiz["id"]}
    fronteira = {raiz["id"]}
    arestas_brutas = []

    for _ in range(profundidade):
        if not fronteira or len(visitados) >= max_nos:
            break
        placeholders = ", ".join("?" for _ in fronteira)
        edges = conn.execute(
            f"SELECT id, no_origem_id, no_destino_id, valor, percentual_pl, competencia "
            f"FROM cda_edges WHERE no_origem_id IN ({placeholders})",
            list(fronteira),
        ).fetchall()

        proxima_fronteira = set()
        for edge in edges:
            if edge["no_destino_id"] not in visitados:
                if len(visitados) >= max_nos:
                    continue
                visitados.add(edge["no_destino_id"])
                proxima_fronteira.add(edge["no_destino_id"])
            arestas_brutas.append(edge)
            grafo.add_edge(edge["no_origem_id"], edge["no_destino_id"])

        fronteira = proxima_fronteira

    ids = list(grafo.nodes)
    placeholders = ", ".join("?" for _ in ids)
    nos_db = conn.execute(
        f"SELECT id, identificador, nome, classe FROM cda_nodes WHERE id IN ({placeholders})", ids
    ).fetchall()
    nome_por_id = {n["id"]: n["nome"] for n in nos_db}
    classe_por_id = {n["id"]: n["classe"] for n in nos_db}
    identificador_por_id = {n["id"]: n["identificador"] for n in nos_db}

    identificadores = list(identificador_por_id.values())
    risco_por_cnpj = {}
    if identificadores:
        placeholders2 = ", ".join("?" for _ in identificadores)
        for cnpj, risco in conn.execute(
            f"SELECT cnpj, classificacao_risco FROM fundos WHERE cnpj IN ({placeholders2})", identificadores
        ):
            risco_por_cnpj[cnpj] = risco

    conn.close()

    nos = [
        {
            "identificador": identificador_por_id[nid],
            "nome": nome_por_id.get(nid),
            "classe": classe_por_id.get(nid),
            "classificacao_risco": risco_por_cnpj.get(identificador_por_id[nid]),
            "eh_raiz": nid == raiz["id"],
        }
        for nid in grafo.nodes
    ]
    arestas = [
        {
            "origem": identificador_por_id[e["no_origem_id"]],
            "destino": identificador_por_id[e["no_destino_id"]],
            "valor": e["valor"],
            "percentual_pl": e["percentual_pl"],
            "competencia": e["competencia"],
        }
        for e in arestas_brutas
        if e["no_origem_id"] in grafo.nodes and e["no_destino_id"] in grafo.nodes
    ]
    return nos, arestas


# --------------------------------------------------------------------------- #
# Helpers de formatacao
# --------------------------------------------------------------------------- #

def formatar_cnpj(cnpj):
    if not cnpj or len(cnpj) != 14:
        return cnpj or ""
    return f"{cnpj[0:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:14]}"




def cor_por_risco(classificacao_risco):
    return CORES_RISCO.get(classificacao_risco, RISCO_SEM_DADO)


def cor_por_risco_claro(classificacao_risco):
    return CORES_RISCO_CLARO.get(classificacao_risco, CORES_RISCO_CLARO[None])


def _hex_para_rgb(hex_cor):
    hex_cor = hex_cor.lstrip("#")
    return tuple(int(hex_cor[i:i + 2], 16) for i in (0, 2, 4))


_CANVAS_NO = 120
_BADGE_RAIO = 20


@lru_cache(maxsize=None)
def _fonte_selo():
    try:
        return ImageFont.load_default(size=28)
    except TypeError:
        # Pillow antigo sem suporte a "size" no load_default - usa o bitmap fixo mesmo.
        return ImageFont.load_default()


@lru_cache(maxsize=None)
def gerar_imagem_no(classificacao_risco, eh_raiz):
    """Circulo (cor por risco) + selo de alerta sobreposto quando o risco e
    ALTO/MEDIO - reforca visualmente o mesmo dado que ja aparece na borda.
    Gerado com Pillow (sem dependencia de JS/React) e cacheado por combinacao
    risco/raiz, ja que so existem poucas combinacoes possiveis."""
    img = Image.new("RGBA", (_CANVAS_NO, _CANVAS_NO), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cor_fundo = _hex_para_rgb(cor_por_risco_claro(classificacao_risco))
    cor_borda = _hex_para_rgb(cor_por_risco(classificacao_risco))
    largura_borda = 8 if eh_raiz else 5
    margem = largura_borda // 2 + 2
    draw.ellipse(
        [margem, margem, _CANVAS_NO - margem, _CANVAS_NO - margem],
        fill=cor_fundo, outline=cor_borda, width=largura_borda,
    )

    if classificacao_risco in ("ALTO", "MEDIO"):
        cx = _CANVAS_NO - _BADGE_RAIO - 6
        cy = _BADGE_RAIO + 6
        draw.ellipse(
            [cx - _BADGE_RAIO, cy - _BADGE_RAIO, cx + _BADGE_RAIO, cy + _BADGE_RAIO],
            fill=cor_borda, outline=(255, 255, 255, 255), width=4,
        )
        draw.text((cx, cy - 2), "!", fill=(255, 255, 255, 255), anchor="mm", font=_fonte_selo())

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def label_risco(classificacao_risco):
    return LABELS_RISCO.get(classificacao_risco, "Sem classificacao")


def rotulo_curto(nome, limite=26):
    nome = (nome or "").strip()
    return nome if len(nome) <= limite else nome[: limite - 1] + "…"


def largura_por_valor(valor, todos_valores):
    if not todos_valores or max(todos_valores) <= 0:
        return LARGURA_MIN
    log_valor = math.log10(max(valor, 1.0))
    log_max = math.log10(max(max(todos_valores), 1.0))
    if log_max == 0:
        return LARGURA_MIN
    proporcao = min(log_valor / log_max, 1.0)
    return LARGURA_MIN + proporcao * (LARGURA_MAX - LARGURA_MIN)


# --------------------------------------------------------------------------- #
# Componentes da tela
# --------------------------------------------------------------------------- #

def renderizar_topbar():
    st.markdown(
        """
        <div class="rm-topbar">
          <div style="display:flex; align-items:center;">
            <div class="rm-brand">
              <div class="rm-brand-icon">*</div>
              <div>
                <div class="rm-brand-title">RISK MAP</div>
                <div class="rm-brand-sub">FUNDOS DE INVESTIMENTO</div>
              </div>
            </div>
            <div class="rm-nav">
              <div class="rm-nav-item rm-nav-item-ativo">Analise Rapida de Fundo</div>
              <div class="rm-nav-item rm-nav-item-desabilitado">Painel de Monitoramento</div>
              <div class="rm-nav-item rm-nav-item-desabilitado">Lista Negativa</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def renderizar_busca():
    coluna_input, coluna_botao = st.columns([5, 1])
    with coluna_input:
        termo = st.text_input(
            "CNPJ do fundo", placeholder="00.000.000/0001-00", label_visibility="collapsed"
        )
    with coluna_botao:
        analisar = st.button("Analisar", use_container_width=True)

    exemplos = obter_exemplos_cnpj(limite=3)
    if exemplos:
        st.caption("Exemplos: " + " · ".join(formatar_cnpj(c) for c in exemplos))

    if not analisar:
        return

    cnpj = normalizar_cnpj(termo)
    if cnpj is None:
        st.error("Digite um CNPJ valido (14 digitos).")
        return

    if buscar_fundo_por_cnpj(cnpj) is None:
        st.error("Fundo nao encontrado na base.")
        return

    st.session_state[CHAVE_FUNDO_SELECIONADO] = cnpj
    st.rerun()


def renderizar_indicador_investimentos_diretos(cnpj_selecionado, nos, arestas):
    """Conta, por classificacao de risco, os fundos em que o fundo selecionado
    investe diretamente (1 salto no grafo - nao conta o subgrafo inteiro)."""
    risco_por_identificador = {n["identificador"]: n["classificacao_risco"] for n in nos}
    destinos_diretos = {a["destino"] for a in arestas if a["origem"] == cnpj_selecionado}

    contagem = {"ALTO": 0, "MEDIO": 0, "BAIXO": 0}
    for destino in destinos_diretos:
        risco = risco_por_identificador.get(destino)
        if risco in contagem:
            contagem[risco] += 1

    st.markdown(
        f"""
        <div class="rm-invest-diretos">
          Investimentos diretos em fundos:
          <span class="rm-badge rm-badge-alto"><i></i>Alto: {contagem['ALTO']}</span>
          <span class="rm-badge rm-badge-medio"><i></i>Medio: {contagem['MEDIO']}</span>
          <span class="rm-badge rm-badge-baixo"><i></i>Baixo: {contagem['BAIXO']}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def renderizar_grafo():
    cnpj_selecionado = st.session_state.get(CHAVE_FUNDO_SELECIONADO)
    if not cnpj_selecionado:
        st.markdown(
            """
            <div class="rm-empty">
              <div class="rm-empty-icon">&#9671;</div>
              <div>Informe o CNPJ do fundo para iniciar a analise de risco</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    nos, arestas = construir_subgrafo(cnpj_selecionado)

    if not nos:
        st.warning("Este fundo ainda nao aparece na base de CDA (composicao e diversificacao de aplicacoes).")
        return

    raiz = next((n for n in nos if n["eh_raiz"]), nos[0])
    if raiz["classificacao_risco"] == "ALTO":
        st.markdown(
            """
            <div class="rm-alert-alto">
              <span class="rm-alert-pill">RISCO ALTO</span>
              <span class="rm-alert-texto">Risco ALTO identificado nesta cadeia
              (troca frequente de prestadores). Ver motivo detalhado no painel a direita.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(f'<div class="rm-graph-stats"><b>{len(nos)}</b> Fundos</div>', unsafe_allow_html=True)
    renderizar_indicador_investimentos_diretos(cnpj_selecionado, nos, arestas)

    if not arestas:
        st.info("Este fundo nao possui posicoes em cotas de outros fundos na competencia mais recente disponivel.")
        return

    st.markdown(
        '<div class="rm-graph-hint">Scroll para zoom &middot; Arrastar para mover '
        '&middot; Clique num fundo para ver os investimentos diretos dele</div>',
        unsafe_allow_html=True,
    )

    nodes = []
    for no in nos:
        tamanho = 34 if no["eh_raiz"] else 22
        nodes.append(
            Node(
                id=no["identificador"],
                label=rotulo_curto(no["nome"] or no["identificador"]),
                shape="image",
                image=gerar_imagem_no(no["classificacao_risco"], no["eh_raiz"]),
                size=tamanho,
                font={"size": 11, "color": "#4a4540", "vadjust": tamanho + 8, "face": "arial"},
                title=(
                    f"{no['nome'] or ''}\nCNPJ: {no['identificador']}\n"
                    f"Classe: {no['classe'] or 'N/D'}\nRisco: {no['classificacao_risco'] or 'sem classificacao'}"
                ),
            )
        )

    valores = [float(a["valor"]) for a in arestas]
    edges = [
        Edge(
            source=a["origem"],
            target=a["destino"],
            color={"color": "#D8D3CE", "opacity": 0.9, "highlight": "#B0A9A4"},
            width=largura_por_valor(float(a["valor"]), valores),
            dashes=True,
            smooth={"type": "continuous"},
            arrows={"to": {"enabled": True, "scaleFactor": 0.5}},
            label=f"{a['percentual_pl']:.1f}%" if a["percentual_pl"] is not None else None,
            font={"size": 10, "color": "#6b6560", "align": "top", "background": "#ffffff", "strokeWidth": 0},
            title=(
                f"Valor: R$ {a['valor']:,.2f}\n% do PL: {a['percentual_pl']:.2f}%\nCompetencia: {a['competencia']}"
                if a["percentual_pl"] is not None
                else f"Valor: R$ {a['valor']:,.2f}\nCompetencia: {a['competencia']}"
            ),
        )
        for a in arestas
    ]

    graph_config = Config(
        height=560, width="100%", directed=True,
        physics=False, hierarchical=True,
        direction="UD", sortMethod="hubsize", shakeTowards="roots",
        levelSeparation=170, nodeSpacing=160, treeSpacing=240,
    )
    clicado = agraph(nodes=nodes, edges=edges, config=graph_config)

    renderizar_legenda()

    if clicado and clicado != cnpj_selecionado:
        st.session_state[CHAVE_FUNDO_SELECIONADO] = clicado
        st.rerun()


def renderizar_legenda():
    itens_legenda = (
        ("Sem classificacao", RISCO_SEM_DADO),
        ("Risco baixo", RISCO_BAIXO),
        ("Risco medio", RISCO_MEDIO),
        ("Risco alto", RISCO_ALTO),
    )
    itens_html = "".join(
        f'<div class="rm-legenda-item"><i style="background:{cor}"></i>{rotulo}</div>'
        for rotulo, cor in itens_legenda
    )
    st.markdown(f'<div class="rm-legenda">{itens_html}</div>', unsafe_allow_html=True)


def renderizar_painel():
    cnpj_selecionado = st.session_state.get(CHAVE_FUNDO_SELECIONADO)
    if not cnpj_selecionado:
        st.markdown('<div class="rm-empty" style="padding:40px 10px;">Nenhum fundo selecionado.</div>', unsafe_allow_html=True)
        return

    fundo = buscar_fundo_por_cnpj(cnpj_selecionado)
    if fundo is None:
        st.error("Fundo nao encontrado.")
        return

    badge_classe = BADGE_CSS_CLASSE.get(fundo["classificacao_risco"], "rm-badge-semdado")
    st.markdown(
        f"""
        <div class="rm-panel-cnpj">{formatar_cnpj(fundo['cnpj'])}</div>
        <div class="rm-panel-nome">{fundo['denominacao_social']}</div>
        <div class="rm-panel-tipo">{fundo['tipo_classe'] or fundo['classe'] or 'N/D'}</div>
        <span class="rm-badge {badge_classe}"><i></i>{label_risco(fundo['classificacao_risco'])}</span>
        """,
        unsafe_allow_html=True,
    )
    if fundo["motivo_classificacao_risco"]:
        st.caption(fundo["motivo_classificacao_risco"])

    with st.container(border=True):
        st.markdown('<div class="rm-section-label">Prestadores de Servico</div>', unsafe_allow_html=True)
        _campo("Administrador", fundo["administrador_nome"] or "N/D")
        _campo("Gestor", fundo["gestor_nome"] or "N/D")
        _campo("Auditor", fundo["auditor_nome"] or "N/D")
        _campo("Custodiante", fundo["custodiante_nome"] or "N/D")
        _campo("Exercicio Social", fundo["exercicio_social_fim"] or "N/D")
        if fundo["fundo_cnpj_pai"]:
            _campo("Fundo Guarda-chuva (CNPJ)", formatar_cnpj(fundo["fundo_cnpj_pai"]))

    with st.container(border=True):
        st.markdown('<div class="rm-section-label">Historico de Prestadores</div>', unsafe_allow_html=True)
        historico = obter_historico_prestadores(cnpj_selecionado)
        if not historico:
            st.caption("Sem historico de prestadores anteriores registrado para este fundo.")
        else:
            for item in historico:
                _card_historico(item)

    with st.container(border=True):
        st.markdown('<div class="rm-section-label">Demonstracao Financeira</div>', unsafe_allow_html=True)
        renderizar_demonstracao_financeira(cnpj_selecionado)

    with st.container(border=True):
        st.markdown('<div class="rm-section-label">Fatos Relevantes (0 critico(s))</div>', unsafe_allow_html=True)
        st.caption("Nenhum fato relevante carregado ainda para este fundo.")


def _campo(rotulo, valor):
    st.markdown(
        f'<div class="rm-field-row"><span class="rm-field-label">{rotulo}</span>'
        f'<span class="rm-field-value">{valor}</span></div>',
        unsafe_allow_html=True,
    )


def _card_historico(item):
    periodo = f"{item['data_inicio']} &rarr; {item['data_fim'] or 'N/D'}"
    st.markdown(
        f"""
        <div class="rm-hist-card">
          <div class="rm-hist-nome">{item['nome']}</div>
          <div class="rm-hist-tipo">{item['tipo_prestador'].capitalize()} <span class="rm-pill-anterior">Anterior</span></div>
          <div class="rm-hist-periodo">{periodo}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def renderizar_demonstracao_financeira(cnpj_selecionado):
    linhas = obter_demonstracoes_todas(cnpj_selecionado)
    if not linhas:
        st.caption("Nenhuma demonstracao financeira carregada ainda para este fundo.")
        return

    # O marcador sintetico (NOVO/DENTRO_DO_PRAZO/ATRASO) sinaliza a situacao do
    # exercicio mais recente e pode conviver com DF real de anos anteriores -
    # como ano_referencia dele e sempre o mais recente (ver sincronizar_situacao_df),
    # a ordenacao ja garante que aparece primeiro na lista.
    for linha in linhas:
        if linha["opiniao_auditor"] in SITUACAO_DF_SINTETICA:
            _card_situacao_sintetica(linha)
        else:
            _card_demonstracao(linha)


def _card_situacao_sintetica(linha):
    rotulo, badge_classe = SITUACAO_DF_SINTETICA[linha["opiniao_auditor"]]
    st.markdown(
        f"""
        <div class="rm-df-card">
          <div class="rm-df-header">
            <span class="rm-df-titulo">Situacao da DF &middot; {linha['ano_referencia']}</span>
            <span class="rm-badge {badge_classe}"><i></i>{rotulo}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _card_demonstracao(linha):
    opiniao = linha["opiniao_auditor"]
    rotulo_opiniao = OPINIAO_LABELS.get(opiniao, "Nao informada")
    badge_classe = OPINIAO_BADGE_CLASSE.get(opiniao, "rm-badge-semdado")
    tipo_rotulo = TIPO_DEMONSTRACAO_LABELS.get(linha["tipo_demonstracao"], linha["tipo_demonstracao"])

    # Descricao/potencial risco so fazem sentido para opinioes modificadas -
    # e so vem preenchidos depois que o modulo de IA processar a DF.
    bloco_ressalva = ""
    if opiniao in OPINIOES_COM_RESSALVA:
        descricao = linha["descricao_opiniao_modificada"] or "A preencher (aguardando analise de IA)."
        potencial_risco = linha["potencial_risco_investidor"] or "A preencher (aguardando analise de IA)."
        bloco_ressalva = f"""
          <div class="rm-df-desc-label">DESCRICAO DA OPINIAO MODIFICADA</div>
          <div class="rm-df-desc-texto">{descricao}</div>
          <div class="rm-df-risco-box">
            <div class="rm-df-risco-titulo">&#9888; Potencial Risco ao Fundo Investidor</div>
            <div class="rm-df-risco-texto">{potencial_risco}</div>
          </div>
        """

    st.markdown(
        f"""
        <div class="rm-df-card">
          <div class="rm-df-header">
            <span class="rm-df-titulo">{tipo_rotulo} &middot; {linha['ano_referencia']}</span>
            <span class="rm-badge {badge_classe}"><i></i>{rotulo_opiniao}</span>
          </div>
          {bloco_ressalva}
        </div>
        """,
        unsafe_allow_html=True,
    )


def renderizar():
    """Monta a tela inteira: topbar, busca e o corpo em 2 colunas (grafo | painel)."""
    st.markdown(CSS, unsafe_allow_html=True)
    renderizar_topbar()
    renderizar_busca()

    coluna_grafo, coluna_painel = st.columns([2.5, 1.3])
    with coluna_grafo:
        renderizar_grafo()
    with coluna_painel:
        renderizar_painel()
