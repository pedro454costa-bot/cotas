"""Roda o prompt de analise de opiniao na LLM (GPT-5 mini) sobre uma amostra.

Le o prompt de pipeline/prompt_analise_opiniao.md, quebra no marcador
"# RELATORIO A ANALISAR" e usa a parte de cima como mensagem de sistema. Essa
divisao nao e cosmetica: o prefixo fixo (~2.000 tokens de matriz) e identico em
todas as chamadas e responde por ~73% do custo total, entao ele precisa ficar
byte a byte igual para o prompt caching da OpenAI pegar. Qualquer coisa variavel
antes dele - CNPJ, nome do fundo - quebraria o cache de todas as linhas.

A saida e um Excel com as MESMAS colunas da entrada mais cinco: as quatro
respostas da IA (prefixo ia_) e ia_erro. Nada da entrada e alterado ou renomeado,
para conferencia lado a lado com a sua classificacao manual.

Requer OPENAI_API_KEY no ambiente.

Uso:
    set OPENAI_API_KEY=sk-...
    python pipeline/12_sob_demanda_testar_llm_opiniao.py
    python pipeline/12_sob_demanda_testar_llm_opiniao.py --limite 10
    python pipeline/12_sob_demanda_testar_llm_opiniao.py --workers 8
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

CAMINHO_PROMPT = config.BASE_DIR / "pipeline" / "prompt_analise_opiniao.md"
ENTRADA_PADRAO = config.BASE_DIR / "exports" / "amostra_teste_llm_100.xlsx"
SAIDA_PADRAO = config.BASE_DIR / "exports" / "amostra_teste_llm_100_resultado.xlsx"

MARCADOR_RELATORIO = "# RELATÓRIO A ANALISAR"
MODELO = "gpt-5-mini"

# Preco USD por 1M tokens - so para estimar o custo da rodada no fim.
PRECO_INPUT, PRECO_INPUT_CACHE, PRECO_OUTPUT = 0.25, 0.025, 2.00

TENTATIVAS = 3
CHECKPOINT_A_CADA = 250   # salva parcial a cada N linhas numa rodada longa
ESPERA_BASE_SEGUNDOS = 2

# Schema com strict=True: a OpenAI passa a garantir o formato na decodificacao,
# entao enum invalido e campo faltando deixam de ser possiveis - nao so improvaveis.
# MEDIO sem acento de proposito: acento em enum e fonte silenciosa de divergencia
# na hora de cruzar com a planilha.
SCHEMA_RESPOSTA: Dict[str, Any] = {
    "name": "analise_opiniao_auditor",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["manifestacao", "classificacao", "justificativa", "impacto"],
        "properties": {
            "manifestacao": {
                "type": "string",
                # ENCERRAMENTO separa o fundo que JA ACABOU (resgate total,
                # liquidacao) do fundo vivo com duvida sobre continuar. Sem essa
                # distincao, ~2.300 linhas da base viravam ALTO indevidamente:
                # nao usar o pressuposto de continuidade e consequencia contabil
                # normal do fim do fundo, nao alerta de risco.
                "enum": ["SEM_RESSALVA", "ENCERRAMENTO", "ENFASE_OUTROS",
                         "CONTINUIDADE", "RESSALVA", "ADVERSA", "ABSTENCAO"],
            },
            "classificacao": {
                "type": "string",
                "enum": ["BAIXO", "MEDIO", "ALTO", "INDETERMINADO"],
            },
            "justificativa": {"type": "string"},
            "impacto": {"type": "string"},
        },
    },
}

COLUNAS_SAIDA = ["ia_manifestacao", "ia_classificacao", "ia_justificativa", "ia_impacto", "ia_erro"]

SECOES_RELATORIO = [
    ("[OPINIÃO]", "trecho_opiniao_secao"),
    ("[BASE PARA OPINIÃO]", "trecho_base_opiniao"),
    ("[ÊNFASE / OUTROS ASSUNTOS]", "trecho_enfase_outros"),
]


def carregar_env() -> None:
    """Le o .env da raiz para o ambiente, sem sobrescrever variavel ja definida.

    Parser proprio de 10 linhas em vez de python-dotenv: o projeto tem poucas
    dependencias de proposito e o formato aqui e uma linha CHAVE=valor.
    O .env esta no .gitignore - a chave nunca deve ser commitada.
    """
    caminho = config.BASE_DIR / ".env"
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip("\"'"))


def carregar_prompt_sistema() -> str:
    """Tudo acima do marcador do relatorio - a parte fixa, cacheavel."""
    texto = CAMINHO_PROMPT.read_text(encoding="utf-8")
    if MARCADOR_RELATORIO not in texto:
        raise RuntimeError(f"Marcador '{MARCADOR_RELATORIO}' nao encontrado em {CAMINHO_PROMPT}")
    return texto.split(MARCADOR_RELATORIO)[0].rstrip()


def montar_relatorio(linha: pd.Series) -> str:
    """Junta os trechos recortados; secao vazia e omitida inteira.

    Mandar o rotulo com nada embaixo faz a LLM tratar a ausencia como informacao
    ("nao ha enfase"), quando na verdade e so recorte que nao encontrou a secao.
    """
    partes = []
    for rotulo, coluna in SECOES_RELATORIO:
        valor = str(linha.get(coluna) or "").strip()
        if valor and valor.lower() != "nan":
            partes.append(f"{rotulo}\n{valor}")
    return "\n\n".join(partes)


def analisar(cliente, sistema: str, relatorio: str, modelo: str,
             reasoning: Optional[str] = None) -> Tuple[Dict[str, Any], Any]:
    """Uma chamada, com retry em falha transitoria. Devolve (resposta, uso).

    reasoning controla quanto o modelo "pensa" antes de responder (minimal/low/
    medium/high). Na rodada medium, 85% dos tokens de saida foram raciocinio
    invisivel - e como a matriz do prompt ja externaliza o raciocinio, esforco
    menor tende a dar o mesmo resultado por uma fracao do preco. Vale so para a
    familia GPT-5; modelos sem raciocinio (4.1) ignoram e o parametro nao e enviado.
    """
    extras: Dict[str, Any] = {"reasoning_effort": reasoning} if reasoning else {}
    ultimo_erro: Optional[Exception] = None
    for tentativa in range(TENTATIVAS):
        try:
            resposta = cliente.chat.completions.create(
                model=modelo,
                messages=[
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": relatorio},
                ],
                response_format={"type": "json_schema", "json_schema": SCHEMA_RESPOSTA},
                **extras,
            )
            return json.loads(resposta.choices[0].message.content), resposta.usage
        except Exception as exc:
            ultimo_erro = exc
            if tentativa < TENTATIVAS - 1:
                time.sleep(ESPERA_BASE_SEGUNDOS * (2 ** tentativa))
    raise ultimo_erro  # type: ignore[misc]


def processar_linha(args) -> Dict[str, Any]:
    indice, linha, cliente, sistema, modelo, reasoning = args
    relatorio = montar_relatorio(linha)

    if len(relatorio) < 200:
        return {"_i": indice, "ia_classificacao": "INDETERMINADO",
                "ia_erro": "texto insuficiente para analise", "_uso": None}

    try:
        dados, uso = analisar(cliente, sistema, relatorio, modelo, reasoning)
        return {
            "_i": indice,
            "ia_manifestacao": dados["manifestacao"],
            "ia_classificacao": dados["classificacao"],
            "ia_justificativa": dados["justificativa"],
            "ia_impacto": dados["impacto"],
            "ia_erro": None,
            "_uso": uso,
        }
    except Exception as exc:
        return {"_i": indice, "ia_classificacao": "INDETERMINADO",
                "ia_erro": str(exc)[:500], "_uso": None}


def resumir_custo(usos) -> None:
    """Confere o custo real da rodada contra a estimativa - inclusive o cache."""
    entrada = sum(u.prompt_tokens for u in usos)
    saida = sum(u.completion_tokens for u in usos)
    cache = sum(getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0 for u in usos)
    nao_cache = entrada - cache

    custo = (nao_cache * PRECO_INPUT + cache * PRECO_INPUT_CACHE + saida * PRECO_OUTPUT) / 1e6
    print(f"\ntokens  entrada {entrada:,} (cache {cache:,} = {cache/entrada:.0%})  saida {saida:,}")
    print(f"custo desta rodada: US$ {custo:.4f}")
    if usos:
        print(f"extrapolado para 15.048 linhas: US$ {custo / len(usos) * 15048:.2f}")


def testar(entrada: Path, saida: Path, limite: Optional[int], workers: int,
           modelo: str, reasoning: Optional[str]) -> None:
    carregar_env()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY nao encontrada. Crie um arquivo .env na raiz do projeto "
            "com a linha: OPENAI_API_KEY=sk-..."
        )
    from openai import OpenAI

    cliente = OpenAI()
    sistema = carregar_prompt_sistema()
    df = pd.read_excel(entrada)
    if limite:
        df = df.head(limite)

    print(f"{len(df)} linhas | modelo {modelo} | reasoning {reasoning or '(padrao)'} "
          f"| prompt fixo {len(sistema):,} chars")
    inicio = time.monotonic()

    tarefas = [(i, linha, cliente, sistema, modelo, reasoning) for i, linha in df.iterrows()]
    resultados = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, resultado in enumerate(pool.map(processar_linha, tarefas), 1):
            resultados.append(resultado)
            marca = "ERRO" if resultado.get("ia_erro") else resultado.get("ia_classificacao", "")
            print(f"[{n}/{len(df)}] {marca}", flush=True)

            # Checkpoint: numa rodada de milhares de linhas, queda de rede no fim
            # jogaria fora tudo que ja foi pago. O parcial e descartavel - o
            # arquivo final e escrito normalmente ao terminar.
            if n % CHECKPOINT_A_CADA == 0:
                parcial = saida.with_name(saida.stem + "_parcial.xlsx")
                pd.DataFrame([{k: v for k, v in r.items() if k != "_uso"}
                              for r in resultados]).to_excel(parcial, index=False)
                print(f"  ... checkpoint: {n} linhas em {parcial.name}", flush=True)

    usos = [r.pop("_uso") for r in resultados]
    respostas = pd.DataFrame(resultados).set_index("_i")

    # Colunas da entrada intactas; as da IA vao no fim.
    final = df.join(respostas)
    for coluna in COLUNAS_SAIDA:
        if coluna not in final.columns:
            final[coluna] = None
    final = final[list(df.columns) + COLUNAS_SAIDA]

    saida.parent.mkdir(parents=True, exist_ok=True)
    final.to_excel(saida, index=False)

    print(f"\n{time.monotonic() - inicio:.0f}s -> {saida}")
    print("\nclassificacao da IA:")
    print(final["ia_classificacao"].value_counts(dropna=False).to_string())
    print("\nIA x regex (tipo_opiniao_detectado):")
    print(pd.crosstab(final["tipo_opiniao_detectado"].fillna("(vazio)"),
                      final["ia_manifestacao"].fillna("(erro)")).to_string())

    erros = final["ia_erro"].notna().sum()
    if erros:
        print(f"\n{erros} linha(s) com erro")
    resumir_custo([u for u in usos if u is not None])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", type=Path, default=ENTRADA_PADRAO)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--modelo", default=MODELO)
    parser.add_argument("--reasoning", default=None,
                        choices=["minimal", "low", "medium", "high"],
                        help="esforco de raciocinio (so familia GPT-5)")
    args = parser.parse_args()
    testar(args.entrada, args.saida, args.limite, args.workers, args.modelo, args.reasoning)
