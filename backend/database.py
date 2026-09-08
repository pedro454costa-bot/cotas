"""Acesso ao SQLite - conexao por requisicao, somente leitura na API.

A API nao escreve no banco (exceto o status do analista, em servico proprio).
Quem escreve sao os pipelines. Por isso a conexao abre em modo read-only via URI:
um bug numa rota nao consegue corromper a base.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence

import config


def _conectar(somente_leitura: bool = True) -> sqlite3.Connection:
    if somente_leitura:
        conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def conexao(somente_leitura: bool = True) -> Iterator[sqlite3.Connection]:
    conn = _conectar(somente_leitura)
    try:
        yield conn
    finally:
        conn.close()


def consultar(sql: str, parametros: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    """Lista de dicts - o que o FastAPI serializa direto para JSON."""
    with conexao() as conn:
        return [dict(linha) for linha in conn.execute(sql, parametros)]


def consultar_um(sql: str, parametros: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
    with conexao() as conn:
        linha = conn.execute(sql, parametros).fetchone()
        return dict(linha) if linha else None


def executar(sql: str, parametros: Sequence[Any] = ()) -> int:
    """Escrita - usada apenas pelo fluxo de status do analista."""
    with conexao(somente_leitura=False) as conn:
        cursor = conn.execute(sql, parametros)
        conn.commit()
        return cursor.rowcount


def placeholders(quantidade: int) -> str:
    """'?, ?, ?' para clausulas IN montadas dinamicamente."""
    return ", ".join("?" * quantidade)
