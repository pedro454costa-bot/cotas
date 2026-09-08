"""Gera uma copia enxuta do banco, para levar a outra maquina.

O cotas.db tem 441 MB, mas 244 MB sao os textos brutos extraidos dos PDFs
(fontes_opiniao_extracao.trecho_*). Esses textos servem ao pipeline da IA e a
mais nada: a tela nunca os le - ela usa a analise ja pronta em opiniao_ia.

Este script copia o banco, esvazia so essas colunas e roda VACUUM. O resultado
abre na aplicacao exatamente igual, com uma fracao do tamanho.

Se um dia for preciso reanalisar PDFs na maquina de destino, use --completo e
leve o banco inteiro - ou reextraia por la com o pipeline 06.

Uso:
    python pipeline/14_sob_demanda_exportar_banco.py
    python pipeline/14_sob_demanda_exportar_banco.py --completo
    python pipeline/14_sob_demanda_exportar_banco.py --zip
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

SAIDA_PADRAO = config.BASE_DIR / "db" / "cotas_distribuicao.db"

# Colunas que so o pipeline de IA consome. Esvaziadas na copia enxuta.
# Formato: (tabela, [colunas])
COLUNAS_PESADAS: List[Tuple[str, List[str]]] = [
    ("fontes_opiniao_extracao", [
        "trecho_opiniao", "trecho_opiniao_secao",
        "trecho_base_opiniao", "trecho_enfase_outros", "secoes_adicionais",
    ]),
    ("demonstracoes_extracao", ["trecho_opiniao"]),
]

# Tabelas de log: nao servem a nada no destino e so ocupam espaco.
TABELAS_DESCARTAVEIS = ["logs_pipeline"]


def megabytes(caminho: Path) -> float:
    return caminho.stat().st_size / 1048576


def enxugar(caminho: Path) -> None:
    conn = sqlite3.connect(caminho)
    try:
        for tabela, colunas in COLUNAS_PESADAS:
            existentes = {r[1] for r in conn.execute(f'PRAGMA table_info("{tabela}")')}
            alvo = [c for c in colunas if c in existentes]
            if not alvo:
                continue
            atribuicoes = ", ".join(f'"{c}" = NULL' for c in alvo)
            conn.execute(f'UPDATE "{tabela}" SET {atribuicoes}')
            print(f"  esvaziado  {tabela}.{{{', '.join(alvo)}}}")

        for tabela in TABELAS_DESCARTAVEIS:
            conn.execute(f'DELETE FROM "{tabela}"')
            print(f"  limpo      {tabela}")

        conn.commit()
        # VACUUM reescreve o arquivo sem as paginas liberadas. Sem ele o arquivo
        # continua do mesmo tamanho, so com espaco livre por dentro.
        print("  compactando (VACUUM)...")
        conn.execute("VACUUM")
    finally:
        conn.close()


def conferir(caminho: Path) -> None:
    """Garante que a copia ainda responde as consultas que a tela faz."""
    conn = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    checagens = [
        ("fundos", "SELECT COUNT(*) FROM fundos"),
        ("fundos com risco", "SELECT COUNT(*) FROM fundos WHERE classificacao_risco IS NOT NULL"),
        ("analises da IA", "SELECT COUNT(*) FROM opiniao_ia"),
        ("arestas CDA", "SELECT COUNT(*) FROM cda_edges"),
        ("prestadores", "SELECT COUNT(*) FROM prestadores_historico"),
    ]
    print("\n  conferencia:")
    for rotulo, sql in checagens:
        print(f"    {rotulo:22} {conn.execute(sql).fetchone()[0]:>9,}")
    conn.close()


def compactar(caminho: Path) -> Path:
    destino = caminho.with_suffix(".db.zip")
    print(f"\n  compactando em {destino.name}...")
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(caminho, caminho.name)
    return destino


def exportar(saida: Path, completo: bool, zipar: bool) -> None:
    origem = config.DB_PATH
    print(f"origem: {origem.name} ({megabytes(origem):.0f} MB)")

    saida.parent.mkdir(parents=True, exist_ok=True)
    print(f"copiando para {saida.name}...")
    shutil.copy2(origem, saida)

    if completo:
        print("  --completo: mantendo os textos dos PDFs")
    else:
        enxugar(saida)

    conferir(saida)
    print(f"\n  resultado: {saida} ({megabytes(saida):.0f} MB)")

    if zipar:
        arquivo = compactar(saida)
        print(f"  zip: {arquivo.name} ({megabytes(arquivo):.0f} MB)")

    print("\nNa maquina de destino, renomeie para cotas.db dentro da pasta db/.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    parser.add_argument("--completo", action="store_true",
                        help="mantem os textos dos PDFs (banco inteiro)")
    parser.add_argument("--zip", dest="zipar", action="store_true",
                        help="gera tambem um .zip do resultado")
    args = parser.parse_args()
    exportar(args.saida, args.completo, args.zipar)
