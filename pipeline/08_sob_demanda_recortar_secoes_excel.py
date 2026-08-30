"""Reprocessa um export de extracao de opiniao, recortando as secoes corretamente.

O export gerado pela versao antiga do 06 trazia, em trecho_opiniao_secao, a janela
bruta de 6000 caracteres a partir do cabecalho do relatorio (praticamente o PDF
inteiro em texto: capa, sumario, papel timbrado) e deixava trecho_base_opiniao
vazio sempre que o titulo nao era literalmente "Base para opiniao" - o que
acontece em todo relatorio com ressalva, adversa ou abstencao de opiniao.

Este script le o Excel existente e reaplica o recorte de pipeline/opiniao_secoes.py
lendo o PDF do cache local (caminho_pdf). A releitura do PDF e necessaria - nao da
para so reaproveitar as colunas antigas - porque a janela antiga era cortada logo
depois da "Base para opiniao", e as secoes de Enfase / Incerteza / Outros assuntos
ficam justamente depois disso. Quando o PDF nao esta no cache, cai de volta para a
janela antiga (recupera opiniao e base, mas nao as secoes adicionais).

Como o gargalo e o parsing do PDF (CPU, nao rede), roda em pool de PROCESSOS.

Gera uma COPIA - o arquivo de entrada nunca e alterado.

Uso:
    python pipeline/08_sob_demanda_recortar_secoes_excel.py exports/resultado_extracao_opiniao_19419_20260816.xlsx
    python pipeline/08_sob_demanda_recortar_secoes_excel.py entrada.xlsx --saida exports/corrigido.xlsx
    python pipeline/08_sob_demanda_recortar_secoes_excel.py entrada.xlsx --workers 8
    python pipeline/08_sob_demanda_recortar_secoes_excel.py entrada.xlsx --sem-pdf   # so a janela antiga (rapido, sem enfase)
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.opiniao_secoes import (
    METODOS_SEM_RECORTE,
    classificar_triagem,
    extrair_secoes,
    recortar_do_pdf,
    remontar_janela,
)

COLUNAS_SECOES = [
    "trecho_opiniao_secao",
    "trecho_base_opiniao",
    "trecho_enfase_outros",
    "secoes_adicionais",
    "titulo_opiniao",
    "titulo_base",
    "tipo_opiniao_detectado",
    "metodo_recorte",
]
COLUNAS_TRIAGEM = ["precisa_llm", "motivo_llm"]
WORKERS_PADRAO = max(1, (os.cpu_count() or 4) - 1)


def janela_da_linha(linha: pd.Series) -> str:
    """Adapta a linha do Excel antigo para o fallback de opiniao_secoes."""
    return remontar_janela(linha.get("trecho_opiniao_secao"), linha.get("trecho_base_opiniao"))


def reprocessar(entrada: Path, saida: Path, usar_pdf: bool, workers: int) -> pd.DataFrame:
    df = pd.read_excel(entrada)
    print(f"Lidas {len(df)} linhas de {entrada.name}")

    secoes = [extrair_secoes(janela_da_linha(linha)) for _, linha in df.iterrows()]

    if usar_pdf and "caminho_pdf" in df.columns:
        caminhos = df["caminho_pdf"].tolist()
        print(f"Relendo {len(caminhos)} PDFs do cache em {workers} processos "
              f"(necessario para achar Enfase/Outros assuntos)...")
        inicio = time.monotonic()
        substituidos = 0
        with ProcessPoolExecutor(max_workers=workers) as executor:
            for posicao, resultado in enumerate(executor.map(recortar_do_pdf, caminhos, chunksize=16)):
                if resultado is not None:
                    secoes[posicao] = resultado
                    substituidos += 1
                if (posicao + 1) % 500 == 0:
                    decorrido = time.monotonic() - inicio
                    restante = decorrido / (posicao + 1) * (len(caminhos) - posicao - 1)
                    print(f"  [{posicao + 1}/{len(caminhos)}] {decorrido / 60:.1f} min decorridos, "
                          f"~{restante / 60:.1f} min restantes", flush=True)
        print(f"  recortados a partir do PDF: {substituidos}/{len(caminhos)} "
              f"em {(time.monotonic() - inicio) / 60:.1f} min")

    triagem = [classificar_triagem(s) for s in secoes]

    saida_df = df.copy()
    novos = pd.DataFrame(secoes, index=saida_df.index)
    for coluna in COLUNAS_SECOES:
        saida_df[coluna] = novos[coluna]
    saida_df["precisa_llm"] = [t[0] for t in triagem]
    saida_df["motivo_llm"] = [t[1] for t in triagem]

    # Deixa o que a LLM vai consumir logo apos a identificacao do fundo.
    prioritarias = COLUNAS_TRIAGEM + COLUNAS_SECOES
    restantes = [c for c in saida_df.columns if c not in prioritarias]
    corte = restantes.index("origem") + 1 if "origem" in restantes else len(restantes)
    saida_df = saida_df[restantes[:corte] + prioritarias + restantes[corte:]]

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida_df.to_excel(saida, index=False)
    return saida_df


def imprimir_resumo(original: pd.DataFrame, corrigido: pd.DataFrame) -> None:
    def chars(*colunas: str) -> int:
        return int(sum(
            corrigido[c].dropna().astype(str).str.len().sum() if c in corrigido else 0
            for c in colunas
        ))

    antes = int(sum(
        original[c].dropna().astype(str).str.len().sum()
        for c in ("trecho_opiniao_secao", "trecho_base_opiniao")
    ))
    marcados = corrigido["precisa_llm"] == "Sim"
    depois_llm = int(sum(
        corrigido.loc[marcados, c].dropna().astype(str).str.len().sum()
        for c in ("trecho_opiniao_secao", "trecho_base_opiniao", "trecho_enfase_outros")
    ))

    print("\n--- tipo_opiniao_detectado ---")
    print(corrigido["tipo_opiniao_detectado"].value_counts(dropna=False).to_string())
    print("\n--- secoes adicionais encontradas ---")
    print(corrigido["secoes_adicionais"].value_counts().head(12).to_string())
    print("\n--- triagem para a LLM ---")
    print(corrigido["motivo_llm"].value_counts().to_string())
    print(f"\n  precisa_llm = Sim: {int(marcados.sum())} de {len(corrigido)} "
          f"({100 * marcados.mean():.1f}%)")
    print("\n--- volume de texto ---")
    print(f"  export antigo (todas as linhas)      : {antes:,} chars")
    print(f"  novo, so as linhas marcadas para LLM : {depois_llm:,} chars "
          f"({100 * (1 - depois_llm / antes):.1f}% a menos)")
    print(f"  total recortado (todas as linhas)    : "
          f"{chars('trecho_opiniao_secao', 'trecho_base_opiniao', 'trecho_enfase_outros'):,} chars")


if __name__ == "__main__":
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not argumentos:
        raise SystemExit("informe o Excel de entrada")

    entrada_path = Path(argumentos[0])
    if "--saida" in sys.argv:
        saida_path = Path(sys.argv[sys.argv.index("--saida") + 1])
    else:
        saida_path = entrada_path.with_name(entrada_path.stem + "_secoes_corrigidas.xlsx")
    num_workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else WORKERS_PADRAO

    df_original = pd.read_excel(entrada_path)
    df_corrigido = reprocessar(entrada_path, saida_path, "--sem-pdf" not in sys.argv, num_workers)
    imprimir_resumo(df_original, df_corrigido)
    print(f"\nGerado: {saida_path}")
