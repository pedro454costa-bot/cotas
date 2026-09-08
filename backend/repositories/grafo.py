"""Subgrafo da cadeia de investimentos (CDA), a partir de um fundo raiz.

Portado do frontend Streamlit, com duas mudancas:

- O percentual do fundo raiz e calculado por multiplicacao ao longo do caminho.
  Numa cadeia master/feeder, saber que o fundo A tem 40% de B nao diz nada; o que
  a area de Risco precisa saber e quanto do patrimonio do fundo ANALISADO esta
  exposto a B, indiretamente.
- O no carrega a classificacao de risco vinda da analise da LLM, nao so o rotulo
  bruto da opiniao.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from backend.database import conexao, placeholders

MAX_NOS = 120
PROFUNDIDADE_PADRAO = 1


def construir(cnpj_raiz: str, profundidade: int = PROFUNDIDADE_PADRAO,
              max_nos: int = MAX_NOS) -> Dict[str, Any]:
    """BFS por cda_edges. Retorna {"nos": [...], "arestas": [...]}.

    profundidade=1 (so investimentos diretos) e o padrao porque com 2+ saltos o
    grafo fica ilegivel em fundo com dezenas de posicoes. Para ir mais fundo, a
    tela recentraliza no no clicado.
    """
    with conexao() as conn:
        raiz = conn.execute(
            "SELECT id FROM cda_nodes WHERE identificador = ? AND tipo_no = 'FUNDO'",
            (cnpj_raiz,),
        ).fetchone()
        if raiz is None:
            return {"nos": [], "arestas": []}

        raiz_id = raiz["id"]
        visitados: Set[int] = {raiz_id}
        fronteira: Set[int] = {raiz_id}
        arestas: List[Dict[str, Any]] = []
        # Fracao do PL do fundo raiz que chega a cada no, acumulada pelo caminho.
        fracao_raiz: Dict[int, float] = {raiz_id: 1.0}

        for _ in range(max(profundidade, 1)):
            if not fronteira or len(visitados) >= max_nos:
                break

            linhas = conn.execute(
                f"""
                SELECT no_origem_id, no_destino_id, valor, percentual_pl, competencia
                FROM cda_edges
                WHERE no_origem_id IN ({placeholders(len(fronteira))})
                ORDER BY valor DESC
                """,
                list(fronteira),
            ).fetchall()

            proxima: Set[int] = set()
            for linha in linhas:
                destino = linha["no_destino_id"]
                if destino not in visitados:
                    if len(visitados) >= max_nos:
                        continue
                    visitados.add(destino)
                    proxima.add(destino)

                origem = linha["no_origem_id"]
                percentual = (linha["percentual_pl"] or 0) / 100.0
                fracao = fracao_raiz.get(origem, 0.0) * percentual
                fracao_raiz[destino] = fracao_raiz.get(destino, 0.0) + fracao

                arestas.append({
                    "origem_id": origem,
                    "destino_id": destino,
                    "valor": linha["valor"],
                    "percentual_pl": linha["percentual_pl"],
                    "percentual_do_raiz": round(fracao * 100, 2),
                    "competencia": linha["competencia"],
                })

            fronteira = proxima

        nos = _detalhar_nos(conn, visitados, raiz_id, fracao_raiz)

    identificador = {no["id"]: no["cnpj"] for no in nos}
    arestas_saida = [
        {
            "origem": identificador[a["origem_id"]],
            "destino": identificador[a["destino_id"]],
            "valor": a["valor"],
            "percentual_pl": a["percentual_pl"],
            "percentual_do_raiz": a["percentual_do_raiz"],
            "competencia": a["competencia"],
        }
        for a in arestas
        if a["origem_id"] in identificador and a["destino_id"] in identificador
    ]
    for no in nos:
        no.pop("id", None)

    return {"nos": nos, "arestas": arestas_saida}


def _detalhar_nos(conn, ids: Set[int], raiz_id: int,
                  fracao_raiz: Dict[int, float]) -> List[Dict[str, Any]]:
    marcadores = placeholders(len(ids))
    linhas = conn.execute(
        f"""
        SELECT n.id, n.identificador, n.nome, n.classe,
               f.denominacao_social, f.classificacao_risco, f.motivo_classificacao_risco,
               f.situacao, f.administrador_nome, f.patrimonio_liquido
        FROM cda_nodes n
        LEFT JOIN fundos f ON f.cnpj = n.identificador
        WHERE n.id IN ({marcadores})
        """,
        list(ids),
    ).fetchall()

    return [
        {
            "id": linha["id"],
            "cnpj": linha["identificador"],
            "nome": linha["denominacao_social"] or linha["nome"],
            "classe": linha["classe"],
            "situacao": linha["situacao"],
            "administrador": linha["administrador_nome"],
            "patrimonio_liquido": linha["patrimonio_liquido"],
            "classificacao_risco": linha["classificacao_risco"],
            "motivo_risco": linha["motivo_classificacao_risco"],
            "percentual_do_raiz": round(fracao_raiz.get(linha["id"], 0.0) * 100, 2),
            "eh_raiz": linha["id"] == raiz_id,
            "no_cadastro": linha["denominacao_social"] is not None,
        }
        for linha in linhas
    ]


def contar_investimentos(cnpj: str) -> Tuple[int, float]:
    """(quantidade de fundos investidos, valor total) - direto, sem montar grafo."""
    with conexao() as conn:
        linha = conn.execute(
            """
            SELECT COUNT(*) AS fundos, COALESCE(SUM(e.valor), 0) AS total
            FROM cda_nodes n
            JOIN cda_edges e ON e.no_origem_id = n.id
            WHERE n.identificador = ? AND n.tipo_no = 'FUNDO'
            """,
            (cnpj,),
        ).fetchone()
    return linha["fundos"], linha["total"]
