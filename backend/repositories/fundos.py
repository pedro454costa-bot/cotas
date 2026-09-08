"""Consultas sobre o cadastro de fundos e seus prestadores."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from backend.database import consultar, consultar_um

CAMPOS_CADASTRO = """
    cnpj, denominacao_social, tp_fundo, classe, classe_anbima, situacao,
    condominio, publico_alvo, data_constituicao, data_registro,
    exercicio_social_inicio, exercicio_social_fim,
    taxa_administracao, taxa_performance, patrimonio_liquido, data_patrimonio_liquido,
    administrador_nome, administrador_cnpj, gestor_nome, gestor_cpf_cnpj,
    auditor_nome, auditor_cnpj, custodiante_nome, controlador_nome,
    fundo_cotas, fundo_exclusivo, classificacao_risco, motivo_classificacao_risco
"""


def normalizar_cnpj(valor: str) -> str:
    """Aceita com ou sem mascara - o banco guarda so digitos."""
    return re.sub(r"\D", "", valor or "")


def formatar_cnpj(cnpj: str) -> str:
    if not cnpj or len(cnpj) != 14:
        return cnpj or ""
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


def obter(cnpj: str) -> Optional[Dict[str, Any]]:
    fundo = consultar_um(f"SELECT {CAMPOS_CADASTRO} FROM fundos WHERE cnpj = ?", (cnpj,))
    if fundo:
        fundo["cnpj_formatado"] = formatar_cnpj(fundo["cnpj"])
    return fundo


def buscar(termo: str, limite: int = 12) -> List[Dict[str, Any]]:
    """Busca por CNPJ (com ou sem mascara) ou por trecho do nome.

    O digito e testado primeiro: quem digita numero quer CNPJ, e um LIKE por nome
    com string numerica so traria ruido.
    """
    termo = (termo or "").strip()
    if len(termo) < 3:
        return []

    digitos = normalizar_cnpj(termo)
    if digitos:
        linhas = consultar(
            f"SELECT {CAMPOS_CADASTRO} FROM fundos WHERE cnpj LIKE ? ORDER BY cnpj LIMIT ?",
            (f"{digitos}%", limite),
        )
        if linhas:
            return [_resumir(linha) for linha in linhas]

    linhas = consultar(
        f"""
        SELECT {CAMPOS_CADASTRO} FROM fundos
        WHERE denominacao_social LIKE ?
        ORDER BY CASE WHEN denominacao_social LIKE ? THEN 0 ELSE 1 END,
                 LENGTH(denominacao_social)
        LIMIT ?
        """,
        (f"%{termo}%", f"{termo}%", limite),
    )
    return [_resumir(linha) for linha in linhas]


def _resumir(fundo: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "cnpj": fundo["cnpj"],
        "cnpj_formatado": formatar_cnpj(fundo["cnpj"]),
        "nome": fundo["denominacao_social"],
        "classe": fundo["classe"],
        "administrador": fundo["administrador_nome"],
        "situacao": fundo["situacao"],
        "classificacao_risco": fundo["classificacao_risco"],
    }


def prestadores_atuais(fundo: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Os prestadores vivem em colunas de `fundos`; aqui viram lista para a tela."""
    mapa = [
        ("Administrador", "administrador_nome", "administrador_cnpj"),
        ("Gestor", "gestor_nome", "gestor_cpf_cnpj"),
        ("Auditor", "auditor_nome", "auditor_cnpj"),
        ("Custodiante", "custodiante_nome", None),
        ("Controlador", "controlador_nome", None),
    ]
    return [
        {"tipo": rotulo, "nome": fundo[campo_nome],
         "documento": fundo.get(campo_doc) if campo_doc else None}
        for rotulo, campo_nome, campo_doc in mapa
        if fundo.get(campo_nome)
    ]


def historico_prestadores(cnpj: str, limite: int = 12) -> List[Dict[str, Any]]:
    """Historico completo, mais recente primeiro, com marcacao do vigente.

    A tela mostra tudo em vez de so o anterior (como fazia o Streamlit): troca de
    auditor logo apos opiniao modificada e sinal de risco, e isso so aparece com
    a linha do tempo inteira.
    """
    return consultar(
        """
        SELECT tipo_prestador, nome, prestador_cnpj, data_inicio, data_fim,
               CASE WHEN data_fim IS NULL OR data_fim = '' THEN 1 ELSE 0 END AS vigente
        FROM prestadores_historico
        WHERE fundo_cnpj = ?
        ORDER BY vigente DESC, data_inicio DESC
        LIMIT ?
        """,
        (cnpj, limite),
    )


def exemplos(limite: int = 3) -> List[Dict[str, Any]]:
    """CNPJs de exemplo para a tela de busca - prioriza fundos com grafo e risco."""
    return consultar(
        """
        SELECT f.cnpj, f.denominacao_social AS nome, f.classificacao_risco
        FROM fundos f
        JOIN cda_nodes n ON n.identificador = f.cnpj AND n.tipo_no = 'FUNDO'
        JOIN cda_edges e ON e.no_origem_id = n.id
        WHERE f.classificacao_risco IS NOT NULL
        GROUP BY f.cnpj
        HAVING COUNT(e.id) BETWEEN 3 AND 12
        LIMIT ?
        """,
        (limite,),
    )


def constelacao(limite: int = 6000) -> List[Dict[str, Any]]:
    """Universo de fundos para a tela de entrada: um ponto por fundo.

    Prioriza quem tem classificacao de risco - sao os pontos coloridos, que dao
    sentido a imagem. O restante entra como poeira cinza ate o limite, so para o
    ceu nao ficar vazio. Ordenar por (tem risco, patrimonio) garante que, se o
    corte apertar, o que sai sao fundos pequenos e sem apontamento.

    Campos minimos de proposito: sao milhares de linhas trafegando, e a tela so
    precisa de cor, tamanho e agrupamento.
    """
    return consultar(
        """
        SELECT cnpj,
               denominacao_social AS nome,
               classe,
               classificacao_risco,
               patrimonio_liquido
        FROM fundos
        WHERE UPPER(situacao) = 'EM FUNCIONAMENTO NORMAL'
           OR classificacao_risco IS NOT NULL
        ORDER BY classificacao_risco IS NULL,
                 COALESCE(patrimonio_liquido, 0) DESC
        LIMIT ?
        """,
        (limite,),
    )
