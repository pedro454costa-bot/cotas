"""Mostra o andamento da extracao de opiniao (06_sob_demanda_extrair_texto_opiniao.py)
enquanto ela roda em background - le o arquivo de status que o processo vai
atualizando a cada documento.

Uso:
    python pipeline/status_extracao_opiniao.py            # olha uma vez e sai
    python pipeline/status_extracao_opiniao.py --watch     # atualiza a cada 10s (Ctrl+C pra sair)
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

ARQUIVO_STATUS = config.RAW_DIR / "status_extracao_opiniao.json"


def formatar_status():
    if not ARQUIVO_STATUS.exists():
        return "Nenhuma extracao rodando ainda (arquivo de status nao existe)."

    corpo = json.loads(ARQUIVO_STATUS.read_text(encoding="utf-8"))

    barra_tamanho = 30
    pct = corpo["percentual"] or 0
    preenchido = int(barra_tamanho * pct / 100)
    barra = "#" * preenchido + "-" * (barra_tamanho - preenchido)

    linhas = [
        f"[{barra}] {pct}%  ({corpo['processados']}/{corpo['alvo_total']})",
        f"Status: {'CONCLUIDO' if corpo['concluido'] else 'RODANDO'}",
        f"Iniciado em: {corpo['iniciado_em']}   Ultima atualizacao: {corpo['atualizado_em']}",
        f"Taxa: {corpo['taxa_por_minuto']} docs/min",
    ]
    if not corpo["concluido"] and corpo["eta_minutos"] is not None:
        horas = int(corpo["eta_minutos"] // 60)
        minutos = int(corpo["eta_minutos"] % 60)
        linhas.append(f"ETA: ~{horas}h{minutos:02d}min restantes")

    linhas.append(f"Por metodo: {corpo['contagem_metodo']}")
    return "\n".join(linhas)


if __name__ == "__main__":
    if "--watch" in sys.argv:
        try:
            while True:
                print("\033c", end="")  # limpa o terminal
                print(formatar_status())
                time.sleep(10)
        except KeyboardInterrupt:
            pass
    else:
        print(formatar_status())
