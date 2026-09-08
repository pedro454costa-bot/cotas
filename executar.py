"""Sobe o Risk Map e abre o navegador.

    python executar.py

Uma aplicacao so: a API e a interface saem da mesma porta, entao nao ha CORS
nem segundo servidor para configurar na maquina do trabalho.
"""

from __future__ import annotations

import threading
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORTA = 8000


def main() -> None:
    endereco = f"http://{HOST}:{PORTA}"
    print(f"Risk Map em {endereco}   (Ctrl+C para parar)")
    # Atraso curto para o navegador nao bater na porta antes do uvicorn subir.
    threading.Timer(1.2, lambda: webbrowser.open(endereco)).start()
    uvicorn.run("backend.api:app", host=HOST, port=PORTA, log_level="warning")


if __name__ == "__main__":
    main()
