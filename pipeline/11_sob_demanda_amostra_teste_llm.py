"""Monta a amostra estratificada de 100 casos para o teste do prompt na LLM.

Amostra aleatoria pura nao serve: 83% da base e opiniao limpa e as opinioes
modificadas - que sao o que interessa - quase nao apareceriam. Aqui o sorteio e
por estrato, sobre-representando os casos raros e as fronteiras da matriz.

ADVERSA entra inteira: so existem 6 em 39.040 linhas.

O arquivo de saida tem EXATAMENTE as mesmas colunas do export original, na mesma
ordem e com os mesmos nomes - e so um recorte de linhas, para conferencia lado a
lado com a base.

Uso:
    python pipeline/11_sob_demanda_amostra_teste_llm.py
    python pipeline/11_sob_demanda_amostra_teste_llm.py --total 200 --semente 7
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

ENTRADA_PADRAO = config.BASE_DIR / "exports" / "base_opiniao_FINAL_36889_v3.xlsx"
SAIDA_PADRAO = config.BASE_DIR / "exports" / "amostra_teste_llm_100.xlsx"

SEMENTE = 42  # sorteio reproduzivel: rodar duas vezes da a mesma amostra

# Proporcao de cada estrato. A soma dos pesos e 100 - o script reescala se o
# --total for outro. ADVERSA fica de fora daqui porque entra integralmente.
ESTRATOS: Dict[str, int] = {
    "ABSTENCAO": 20,             # abstencao de opiniao
    "COM_RESSALVA": 25,          # opiniao com ressalva
    "ENFASE": 25,                # opiniao limpa COM enfase - o caso que o titulo esconde
    "OUTROS_ASSUNTOS": 16,       # outros assuntos / valores correspondentes, sem enfase
    "TIPO_NAO_IDENTIFICADO": 8,  # tem texto, mas o regex nao achou o tipo
}


CHAVE_LINHA = ["cnpj", "ano_referencia", "origem"]


def excluir_amostras(df: pd.DataFrame, caminhos: List[Path]) -> pd.DataFrame:
    """Remove do universo as linhas ja sorteadas em amostras anteriores.

    ADVERSA e a excecao inevitavel: so existem 6 na base inteira, entao elas
    voltam em qualquer amostra. Isso e util - permite comparar duas configuracoes
    do modelo exatamente nas mesmas linhas da classe mais rara.
    """
    if not caminhos:
        return df
    usadas = set()
    for caminho in caminhos:
        anterior = pd.read_excel(caminho)
        usadas |= set(map(tuple, anterior[CHAVE_LINHA].itertuples(index=False, name=None)))

    chaves = list(map(tuple, df[CHAVE_LINHA].itertuples(index=False, name=None)))
    manter = [chave not in usadas or chave[0] is None for chave in chaves]
    e_adversa = (df["tipo_opiniao_detectado"] == "ADVERSA").tolist()
    filtro = [m or a for m, a in zip(manter, e_adversa)]

    removidas = len(df) - sum(filtro)
    print(f"excluidas {removidas} linhas ja usadas em {len(caminhos)} amostra(s) anterior(es)")
    return df[filtro]


def montar_estratos(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Recorta o universo elegivel (precisa_llm=Sim) nos grupos da amostra."""
    universo = df[df["precisa_llm"] == "Sim"].copy()
    tipo = universo["tipo_opiniao_detectado"].fillna("")
    motivo = universo["motivo_llm"].fillna("")
    tem_enfase = motivo.str.contains("enfase", case=False)

    return {
        "ADVERSA": universo[tipo == "ADVERSA"],
        "ABSTENCAO": universo[tipo == "ABSTENCAO"],
        "COM_RESSALVA": universo[tipo == "COM_RESSALVA"],
        # Enfase e "outros assuntos" so viram estrato proprio quando a opiniao esta
        # limpa: com ressalva/abstencao o caso ja foi coberto pelos estratos acima.
        "ENFASE": universo[(tipo == "SEM_RESSALVA") & tem_enfase],
        "OUTROS_ASSUNTOS": universo[(tipo == "SEM_RESSALVA") & ~tem_enfase],
        "TIPO_NAO_IDENTIFICADO": universo[tipo == ""],
    }


def sortear(df: pd.DataFrame, total: int, semente: int) -> pd.DataFrame:
    estratos = montar_estratos(df)

    # ADVERSA inteira - sao 6 no universo, nao ha o que sortear.
    partes: List[pd.DataFrame] = [estratos["ADVERSA"]]
    restante = max(total - len(estratos["ADVERSA"]), 0)
    peso_total = sum(ESTRATOS.values())

    for nome, peso in ESTRATOS.items():
        alvo = round(restante * peso / peso_total)
        disponivel = estratos[nome]
        if disponivel.empty or alvo == 0:
            print(f"  {nome:24} 0 (disponivel: {len(disponivel)})")
            continue
        n = min(alvo, len(disponivel))
        partes.append(disponivel.sample(n=n, random_state=semente))
        print(f"  {nome:24} {n:4} (disponivel: {len(disponivel)})")

    print(f"  {'ADVERSA':24} {len(estratos['ADVERSA']):4} (todas)")
    return pd.concat(partes).sort_values(["tipo_opiniao_detectado", "ano_referencia"])


def gerar_amostra(entrada: Path, saida: Path, total: int, semente: int,
                  excluir: List[Path]) -> None:
    df = pd.read_excel(entrada)
    print(f"base: {len(df):,} linhas ({entrada.name})")
    df = excluir_amostras(df, excluir)
    print(f"\nestratos sorteados (semente {semente}):")

    amostra = sortear(df, total, semente)

    # Mesmas colunas, mesma ordem, mesmos nomes - so um recorte de linhas.
    amostra = amostra[df.columns]
    saida.parent.mkdir(parents=True, exist_ok=True)
    amostra.to_excel(saida, index=False)

    print(f"\ntotal: {len(amostra)} linhas -> {saida}")
    print("\nconferencia por tipo_opiniao_detectado:")
    print(amostra["tipo_opiniao_detectado"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", type=Path, default=ENTRADA_PADRAO)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    parser.add_argument("--total", type=int, default=100)
    parser.add_argument("--semente", type=int, default=SEMENTE)
    parser.add_argument("--excluir", type=Path, nargs="*", default=[],
                        help="amostras anteriores cujas linhas nao devem se repetir")
    args = parser.parse_args()
    gerar_amostra(args.entrada, args.saida, args.total, args.semente, args.excluir)
