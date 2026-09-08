"""Demonstracoes financeiras e a analise da LLM sobre a opiniao do auditor."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.database import consultar, consultar_um, executar, placeholders

STATUS_VALIDOS = ("PENDENTE", "QUESTIONADO", "ESCALADO", "RESOLVIDO")


def demonstracoes(cnpj: str) -> List[Dict[str, Any]]:
    """Historico de DFs do fundo com a analise da IA, mais recente primeiro.

    O LEFT JOIN e proposital: DF entregue sem analise ainda (ano fora do lote
    processado) precisa aparecer na tela como "nao analisada", nunca sumir - e
    tambem nunca ser lida como ausencia de risco.
    """
    return consultar(
        """
        SELECT f.ano_referencia,
               f.origem,
               f.opiniao_estruturada AS opiniao_cvm,
               f.data_entrega,
               f.link_arquivo,
               ia.manifestacao,
               ia.classificacao_risco,
               ia.justificativa,
               ia.impacto,
               ia.divergencia_regex,
               ia.celula_invalida,
               ia.status_analista,
               ia.modelo,
               ia.atualizado_em,
               ia.erro,
               e.tipo_opiniao_detectado
        FROM fontes_opiniao_auditor f
        LEFT JOIN fontes_opiniao_extracao e ON e.fonte_opiniao_id = f.id
        LEFT JOIN opiniao_ia ia ON ia.fonte_opiniao_id = f.id
        WHERE f.fundo_cnpj = ?
        ORDER BY f.ano_referencia DESC, ia.classificacao_risco IS NULL, f.origem
        """,
        (cnpj,),
    )


def analise_mais_recente(cnpj: str) -> Optional[Dict[str, Any]]:
    """A analise que sustenta a classificacao de risco do fundo hoje."""
    return consultar_um(
        """
        SELECT ano_referencia, manifestacao, classificacao_risco, justificativa,
               impacto, divergencia_regex, celula_invalida, status_analista
        FROM opiniao_ia
        WHERE fundo_cnpj = ? AND classificacao_risco IN ('BAIXO','MEDIO','ALTO')
        ORDER BY ano_referencia DESC,
                 CASE classificacao_risco WHEN 'ALTO' THEN 3 WHEN 'MEDIO' THEN 2 ELSE 1 END DESC
        LIMIT 1
        """,
        (cnpj,),
    )


def riscos_por_cnpj(cnpjs: List[str]) -> Dict[str, Dict[str, Any]]:
    """Analise mais recente de varios fundos de uma vez - usado pelo grafo.

    Uma consulta so em vez de N: um grafo de 120 nos faria 120 idas ao banco.
    """
    if not cnpjs:
        return {}
    linhas = consultar(
        f"""
        SELECT fundo_cnpj, ano_referencia, manifestacao, classificacao_risco, justificativa
        FROM opiniao_ia
        WHERE fundo_cnpj IN ({placeholders(len(cnpjs))})
          AND classificacao_risco IN ('BAIXO','MEDIO','ALTO')
        ORDER BY ano_referencia
        """,
        cnpjs,
    )
    # O ORDER BY crescente faz a ultima escrita vencer: fica a mais recente.
    return {linha["fundo_cnpj"]: linha for linha in linhas}


def monitoramento(status: Optional[str] = None, risco: Optional[str] = None,
                  administrador: Optional[str] = None, ano: Optional[int] = None,
                  apenas_revisao: bool = False, limite: int = 300) -> List[Dict[str, Any]]:
    """Fila de trabalho da Tela 2."""
    condicoes = ["ia.classificacao_risco IS NOT NULL"]
    parametros: List[Any] = []

    if status:
        condicoes.append("ia.status_analista = ?")
        parametros.append(status)
    if risco:
        condicoes.append("ia.classificacao_risco = ?")
        parametros.append(risco)
    if administrador:
        condicoes.append("f.administrador_nome LIKE ?")
        parametros.append(f"%{administrador}%")
    if ano:
        condicoes.append("ia.ano_referencia = ?")
        parametros.append(ano)
    if apenas_revisao:
        condicoes.append("(ia.divergencia_regex = 1 OR ia.celula_invalida = 1)")

    parametros.append(limite)
    return consultar(
        f"""
        SELECT ia.id, ia.fundo_cnpj, ia.ano_referencia, ia.manifestacao,
               ia.classificacao_risco, ia.justificativa, ia.impacto,
               ia.status_analista, ia.divergencia_regex, ia.celula_invalida,
               ia.modelo, ia.atualizado_em,
               f.denominacao_social AS nome, f.classe, f.administrador_nome,
               f.gestor_nome, f.situacao
        FROM opiniao_ia ia
        LEFT JOIN fundos f ON f.cnpj = ia.fundo_cnpj
        WHERE {' AND '.join(condicoes)}
        ORDER BY CASE ia.classificacao_risco
                     WHEN 'ALTO' THEN 3 WHEN 'MEDIO' THEN 2 ELSE 1 END DESC,
                 ia.ano_referencia DESC
        LIMIT ?
        """,
        parametros,
    )


def indicadores() -> Dict[str, Any]:
    """Cards do topo da Tela 2."""
    por_status = consultar(
        "SELECT status_analista, COUNT(*) AS total FROM opiniao_ia "
        "WHERE classificacao_risco IS NOT NULL GROUP BY 1"
    )
    por_risco = consultar(
        "SELECT classificacao_risco, COUNT(*) AS total FROM opiniao_ia "
        "WHERE classificacao_risco IS NOT NULL GROUP BY 1"
    )
    revisao = consultar_um(
        "SELECT COUNT(*) AS total FROM opiniao_ia "
        "WHERE divergencia_regex = 1 OR celula_invalida = 1"
    )
    return {
        "total": sum(linha["total"] for linha in por_status),
        "por_status": {linha["status_analista"]: linha["total"] for linha in por_status},
        "por_risco": {linha["classificacao_risco"]: linha["total"] for linha in por_risco},
        "revisao_humana": revisao["total"] if revisao else 0,
    }


def atualizar_status(analise_id: int, status: str) -> bool:
    if status not in STATUS_VALIDOS:
        raise ValueError(f"status invalido: {status}")
    linhas = executar(
        "UPDATE opiniao_ia SET status_analista = ?, "
        "atualizado_em = datetime('now','localtime') WHERE id = ?",
        (status, analise_id),
    )
    return linhas > 0
