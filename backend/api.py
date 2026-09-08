"""API do Risk Map - FastAPI servindo JSON e a interface estatica.

Uma aplicacao so: as rotas /api/* devolvem JSON e o restante serve frontend_web/.
Isso evita CORS, segundo servidor e configuracao de proxy - a tela abre com um
comando e nada mais.

Uso:
    python -m uvicorn backend.api:app --reload
    python executar.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from backend.repositories import fundos as repo_fundos
from backend.repositories import grafo as repo_grafo
from backend.repositories import opiniao as repo_opiniao
from backend.services import risco as servico_risco

DIR_FRONTEND = config.BASE_DIR / "frontend_web"

app = FastAPI(title="Risk Map - Fundos de Investimento", version="1.0.0")


@app.on_event("startup")
def preparar() -> None:
    servico_risco.garantir_estruturas()


# --------------------------------------------------------------------------- #
# Busca e cadastro
# --------------------------------------------------------------------------- #

@app.get("/api/exemplos")
def exemplos():
    return repo_fundos.exemplos()


@app.get("/api/constelacao")
def constelacao(limite: int = Query(6000, le=12000)):
    """Todos os fundos como pontos - a tela de entrada."""
    return repo_fundos.constelacao(limite)


@app.get("/api/busca")
def busca(q: str = Query(..., min_length=3), limite: int = Query(12, le=50)):
    return repo_fundos.buscar(q, limite)


@app.get("/api/fundos/{cnpj}")
def fundo(cnpj: str):
    cnpj = repo_fundos.normalizar_cnpj(cnpj)
    dados = repo_fundos.obter(cnpj)
    if dados is None:
        raise HTTPException(404, "Fundo nao encontrado no cadastro")

    quantidade, valor = repo_grafo.contar_investimentos(cnpj)
    return {
        "cadastro": dados,
        "prestadores": repo_fundos.prestadores_atuais(dados),
        "historico_prestadores": repo_fundos.historico_prestadores(cnpj),
        "investimentos": {"quantidade": quantidade, "valor_total": valor},
        "analise_recente": repo_opiniao.analise_mais_recente(cnpj),
    }


@app.get("/api/fundos/{cnpj}/grafo")
def grafo(cnpj: str, profundidade: int = Query(1, ge=1, le=3)):
    cnpj = repo_fundos.normalizar_cnpj(cnpj)
    dados = repo_grafo.construir(cnpj, profundidade=profundidade)
    if not dados["nos"]:
        raise HTTPException(404, "Fundo sem posicoes na CDA")
    return dados


@app.get("/api/fundos/{cnpj}/demonstracoes")
def demonstracoes(cnpj: str):
    return repo_opiniao.demonstracoes(repo_fundos.normalizar_cnpj(cnpj))


@app.get("/api/fundos/{cnpj}/risco-cadeia")
def risco_cadeia(cnpj: str, profundidade: int = Query(2, ge=1, le=3)):
    return servico_risco.resumo_cadeia(repo_fundos.normalizar_cnpj(cnpj), profundidade)


# --------------------------------------------------------------------------- #
# Painel de monitoramento
# --------------------------------------------------------------------------- #

@app.get("/api/monitoramento/indicadores")
def indicadores():
    return repo_opiniao.indicadores()


@app.get("/api/monitoramento")
def monitoramento(
    status: Optional[str] = None,
    risco: Optional[str] = None,
    administrador: Optional[str] = None,
    ano: Optional[int] = None,
    apenas_revisao: bool = False,
    limite: int = Query(300, le=1000),
):
    return repo_opiniao.monitoramento(status, risco, administrador, ano, apenas_revisao, limite)


class MudancaStatus(BaseModel):
    status: str


@app.put("/api/monitoramento/{analise_id}/status")
def mudar_status(analise_id: int, corpo: MudancaStatus):
    try:
        atualizou = repo_opiniao.atualizar_status(analise_id, corpo.status)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not atualizou:
        raise HTTPException(404, "Analise nao encontrada")
    return {"id": analise_id, "status": corpo.status}


@app.get("/api/lista-negativa")
def lista_negativa():
    return servico_risco.lista_negativa()


# --------------------------------------------------------------------------- #
# Interface estatica - registrada por ultimo para nao capturar /api/*
# --------------------------------------------------------------------------- #

@app.middleware("http")
async def sem_cache(request, proximo):
    """Impede o navegador de servir JS/CSS antigos do cache.

    Sem isso, editar um arquivo do frontend e recarregar a pagina pode continuar
    executando a versao anterior - o sintoma aparece como bug no codigo novo e
    custa muito tempo de diagnostico.
    """
    resposta = await proximo(request)
    if not request.url.path.startswith("/api/"):
        resposta.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resposta


@app.get("/")
def raiz():
    return FileResponse(DIR_FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=DIR_FRONTEND), name="frontend")
