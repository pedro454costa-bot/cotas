"""Entrypoint Streamlit.

Uso:
    streamlit run frontend/app.py
"""

import sys
from pathlib import Path

# Permite rodar como "streamlit run frontend/app.py" (nao como modulo).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from frontend import analise_rapida  # noqa: E402

st.set_page_config(page_title="Risk Map - Fundos de Investimento", page_icon="🔴", layout="wide")

analise_rapida.renderizar()