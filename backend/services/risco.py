"""Regras de risco da cadeia - o que a tela mostra como veredito.

A classificacao de um fundo isolado nao basta para decidir investimento: o risco
chega pela cadeia. Um FIC com opiniao limpa que aloca 68% num fundo com abstencao
carrega o problema do investido, e e essa leitura que a area de Risco precisa ver
antes de aprovar.

Aqui ficam as duas contas que a tela faz:

    resumo_cadeia()  - contadores do cabecalho (lista negativa, opinioes
                       modificadas, fundos na cadeia)
    avaliar()        - o veredito: LIBERADO / ATENCAO / VEDADO
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.database import consultar, executar, placeholders
from backend.repositories import grafo as repo_grafo

# Exposicao minima para um problema na cadeia contar. Posicao de 0,3% num fundo
# com ressalva nao deveria vedar investimento no fundo inteiro.
EXPOSICAO_MINIMA_PCT = 1.0

DDL_LISTA_NEGATIVA = """
CREATE TABLE IF NOT EXISTS lista_negativa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fundo_cnpj TEXT NOT NULL UNIQUE,
    motivo TEXT NOT NULL,
    incluido_por TEXT,
    incluido_em TEXT DEFAULT (datetime('now', 'localtime'))
)
"""


def garantir_estruturas() -> None:
    """A lista negativa e curada pelo analista, nao vem de pipeline."""
    executar(DDL_LISTA_NEGATIVA)


def lista_negativa() -> List[Dict[str, Any]]:
    return consultar(
        """
        SELECT l.fundo_cnpj, l.motivo, l.incluido_por, l.incluido_em,
               f.denominacao_social AS nome, f.administrador_nome
        FROM lista_negativa l
        LEFT JOIN fundos f ON f.cnpj = l.fundo_cnpj
        ORDER BY l.incluido_em DESC
        """
    )


def _cnpjs_na_lista(cnpjs: List[str]) -> Dict[str, str]:
    if not cnpjs:
        return {}
    linhas = consultar(
        f"SELECT fundo_cnpj, motivo FROM lista_negativa "
        f"WHERE fundo_cnpj IN ({placeholders(len(cnpjs))})",
        cnpjs,
    )
    return {linha["fundo_cnpj"]: linha["motivo"] for linha in linhas}


def resumo_cadeia(cnpj: str, profundidade: int = 2) -> Dict[str, Any]:
    """Contadores e veredito da cadeia do fundo.

    Profundidade 2 aqui (e nao 1 como no desenho do grafo): para CONTAR risco
    vale olhar mais fundo, mesmo que para DESENHAR fique ilegivel. O custo e uma
    consulta a mais, e uma cadeia master/feeder de dois saltos e comum.
    """
    dados = repo_grafo.construir(cnpj, profundidade=profundidade)
    nos = [no for no in dados["nos"] if not no["eh_raiz"]]
    na_lista = _cnpjs_na_lista([no["cnpj"] for no in nos] + [cnpj])

    relevantes = [no for no in nos if (no["percentual_do_raiz"] or 0) >= EXPOSICAO_MINIMA_PCT]
    alto = [no for no in relevantes if no["classificacao_risco"] == "ALTO"]
    medio = [no for no in relevantes if no["classificacao_risco"] == "MEDIO"]
    bloqueados = [no for no in nos if no["cnpj"] in na_lista]

    proprio = consultar(
        "SELECT classificacao_risco, motivo_classificacao_risco FROM fundos WHERE cnpj = ?",
        (cnpj,),
    )
    risco_proprio = proprio[0]["classificacao_risco"] if proprio else None

    veredito, mensagem = _decidir(cnpj, risco_proprio, alto, medio, bloqueados, na_lista)

    return {
        "veredito": veredito,
        "mensagem": mensagem,
        "risco_proprio": risco_proprio,
        "contadores": {
            "lista_negativa": len(bloqueados) + (1 if cnpj in na_lista else 0),
            "opiniao_modificada": len(alto) + len(medio),
            "fundos_na_cadeia": len(nos),
        },
        "criticos": [
            {
                "cnpj": no["cnpj"],
                "nome": no["nome"],
                "classificacao_risco": no["classificacao_risco"],
                "motivo": no["motivo_risco"],
                "exposicao_pct": no["percentual_do_raiz"],
                "na_lista_negativa": no["cnpj"] in na_lista,
            }
            for no in sorted(alto + bloqueados,
                             key=lambda n: n["percentual_do_raiz"] or 0, reverse=True)
        ],
    }


def _decidir(cnpj, risco_proprio, alto, medio, bloqueados, na_lista):
    """VEDADO exige risco concreto; ATENCAO cobre o resto; LIBERADO e o silencio."""
    if cnpj in na_lista:
        return "VEDADO", "Este fundo esta na lista negativa."
    if bloqueados:
        nomes = ", ".join(no["nome"] or no["cnpj"] for no in bloqueados[:2])
        return "VEDADO", f"A cadeia deste fundo alcanca fundo em lista negativa: {nomes}."
    if risco_proprio == "ALTO":
        return "VEDADO", "A demonstracao financeira deste fundo tem apontamento de risco alto."
    if alto:
        exposicao = sum(no["percentual_do_raiz"] or 0 for no in alto)
        return "VEDADO", (
            f"Existem riscos criticos na cadeia deste fundo que contraindicam o "
            f"investimento: {len(alto)} fundo(s) de risco alto, {exposicao:.1f}% do patrimonio."
        )
    if medio or risco_proprio == "MEDIO":
        return "ATENCAO", (
            "Ha apontamentos de auditoria na cadeia deste fundo. "
            "Recomenda-se leitura das demonstracoes antes da decisao."
        )
    return "LIBERADO", "Nao foram identificados apontamentos relevantes na cadeia."
