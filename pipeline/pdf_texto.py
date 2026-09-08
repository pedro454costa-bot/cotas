"""Extracao de texto do PDF com reparo de fonte quebrada.

Motivo: 1.302 documentos cairam em "sem_texto_revisar_manual" no export. Ao abrir
os PDFs na mao a opiniao esta la - o que falha e a leitura, nao o documento. Sao
tres defeitos distintos, e nenhum deles se resolve so trocando de biblioteca:

1. ToUnicode ausente/quebrado (tipico de PDF gerado por Word com Calibri
   embarcado como Type0/Identity-H). pypdf e PyMuPDF devolvem
   "WrinCipais assuntos" (na verdade "WƌŝŶĐŝƉĂŝƐ") no lugar de "Principais
   assuntos": o texto existe, mas o mapa glifo->caractere do PDF esta errado. A
   saida e ler o GLYPH ID de cada caractere (PyMuPDF.get_texttrace) e remontar o
   mapa a partir do cmap da fonte - da propria fonte embarcada quando ela traz
   cmap, ou da fonte instalada de mesmo nome quando o subset veio sem cmap
   (mesmo numero de glifos = mesma ordem de glifos).

2. Pagina sem camada de texto (documento escaneado). Nao ha o que consertar sem
   OCR; o modulo apenas marca "sem_texto_scan" para nao confundir com o defeito 1,
   que e recuperavel.

3. Texto sem quebra de linha (a pagina inteira sai grudada, do tipo
   "...Sao Paulo SPOpiniao Examinamos as demonstracoes..."). O texto esta certo;
   quem falha e o recorte por titulo - tratado em opiniao_secoes.py.

pypdf continua como fallback: e ele que o resto do pipeline usa, e ha PDF que o
PyMuPDF recusa e vice-versa.
"""

from __future__ import annotations

import io
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

logging.getLogger("pypdf").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

# Caracteres que denunciam ToUnicode quebrado: o texto "vira" Latim Estendido
# (U+0100-U+02FF) e caracteres de controle baixos no lugar do espaco (\x03).
# U+FFFD entra na lista porque o get_texttrace() do PyMuPDF marca assim o glifo
# que ele nao conseguiu mapear: e o mesmo defeito, visto pelo outro lado da API.
PADRAO_SUSPEITO = re.compile(r"[\u0100-\u02ff\u0001-\u0008\u000b-\u001f\ufffd]")
# Acima disso a linha e ilegivel - nao e so uma palavra com acento incomum.
FRACAO_SUSPEITA_MINIMA = 0.20
MIN_CHARS_TEXTO_UTIL = 200
# Distancia vertical a partir da qual dois spans sao linhas diferentes.
TOLERANCIA_LINHA_PT = 2.0

_DIR_FONTES_SISTEMA = Path("C:/Windows/Fonts")
_ARQUIVOS_FONTE_SISTEMA = {
    "calibri": "calibri.ttf", "calibri-bold": "calibrib.ttf",
    "calibri-italic": "calibrii.ttf", "calibri-bolditalic": "calibriz.ttf",
    "calibri-light": "calibril.ttf",
    "cambria": "cambria.ttc", "cambria-bold": "cambriab.ttf",
    "arialmt": "arial.ttf", "arial-boldmt": "arialbd.ttf",
    "arial-italicmt": "ariali.ttf",
    "timesnewromanpsmt": "times.ttf", "timesnewromanps-boldmt": "timesbd.ttf",
    "verdana": "verdana.ttf", "tahoma": "tahoma.ttf",
    "segoeui": "segoeui.ttf", "corbel": "corbel.ttf",
}


# Ha PDF que renomeia a fonte para "CIDFont+F1" e apaga a familia, entao nao ha
# nome para casar. O numero de glifos identifica a fonte na pratica: dentro de uma
# familia o regular e o negrito compartilham a mesma ordem de glifos, e a ordem e
# a unica coisa de que o mapa precisa. Familias diferentes nao colidem na lista
# acima (Calibri 7048, Arial 4651, Times 4731, ...).
_POR_N_GLIFOS_CACHE: Dict[int, Optional[str]] = {}

# Depois de decodificar, o texto tem de parecer portugues. Sem isso um mapa errado
# passaria despercebido: trocaria lixo visivel por lixo de aparencia inocente.
PADRAO_PALAVRAS_COMUNS = re.compile(
    r"\b(?:de|da|do|das|dos|que|para|com|nao|em|as|os|uma|pela|sobre)\b", re.IGNORECASE
)
MIN_PALAVRAS_COMUNS_POR_MIL = 8


def parece_portugues(texto: str) -> bool:
    """Densidade minima de palavras funcionais - o teste de sanidade do decodificado."""
    if len(texto) < 80:
        return False
    return len(PADRAO_PALAVRAS_COMUNS.findall(texto)) >= MIN_PALAVRAS_COMUNS_POR_MIL * len(texto) / 1000


class TextoPdf(NamedTuple):
    texto: str
    metodo: str
    paginas: int
    paginas_reparadas: int


def _normalizar_nome_fonte(nome: str) -> str:
    """'BDJHDJ+Calibri-Bold' -> 'calibri-bold' (o prefixo e o tag do subset)."""
    return nome.split("+")[-1].replace(" ", "").lower()


def _mapa_de_ttfont(fonte) -> Dict[int, int]:
    """{glyph id -> codepoint} a partir do cmap da fonte."""
    try:
        cmap = fonte.getBestCmap()
    except Exception:
        return {}
    posicao = {nome: i for i, nome in enumerate(fonte.getGlyphOrder())}
    mapa: Dict[int, int] = {}
    for codepoint, nome_glifo in cmap.items():
        gid = posicao.get(nome_glifo)
        if gid is not None:
            mapa.setdefault(gid, codepoint)
    return mapa


def _arquivo_por_n_glifos(n_glifos: int) -> Optional[str]:
    """Fonte instalada com exatamente essa quantidade de glifos, se houver uma so."""
    if not n_glifos:
        return None
    if n_glifos not in _POR_N_GLIFOS_CACHE:
        from fontTools.ttLib import TTFont

        achado = None
        for arquivo in dict.fromkeys(_ARQUIVOS_FONTE_SISTEMA.values()):
            caminho = _DIR_FONTES_SISTEMA / arquivo
            if not caminho.exists():
                continue
            try:
                fonte = TTFont(str(caminho), fontNumber=0, lazy=True)
                if len(fonte.getGlyphOrder()) == n_glifos and "cmap" in fonte:
                    achado = arquivo
                    break
            except Exception:
                continue
        _POR_N_GLIFOS_CACHE[n_glifos] = achado
    return _POR_N_GLIFOS_CACHE[n_glifos]


@lru_cache(maxsize=64)
def _mapa_fonte_sistema(nome_normalizado: str, n_glifos: int) -> Optional[Tuple[Tuple[int, int], ...]]:
    """Mapa da fonte instalada no Windows, so se a contagem de glifos bater.

    Mesma familia + mesmo numero de glifos = mesma versao da fonte, entao os glyph
    ids coincidem. Contagem diferente significa subset reordenado, e ai o mapa do
    sistema produziria texto errado - melhor nao devolver nada."""
    arquivo = _ARQUIVOS_FONTE_SISTEMA.get(nome_normalizado) or _arquivo_por_n_glifos(n_glifos)
    if not arquivo:
        return None
    caminho = _DIR_FONTES_SISTEMA / arquivo
    if not caminho.exists():
        return None
    try:
        from fontTools.ttLib import TTFont

        fonte = TTFont(str(caminho), fontNumber=0, lazy=True)
        if len(fonte.getGlyphOrder()) != n_glifos:
            return None
        return tuple(_mapa_de_ttfont(fonte).items())
    except Exception:
        return None


def _mapa_glifos(documento, xref: int, nome_fonte: str) -> Dict[int, int]:
    """Mapa glyph id -> codepoint: primeiro pela fonte embarcada, depois sistema."""
    try:
        _, _, _, buffer = documento.extract_font(xref)
    except Exception:
        buffer = b""

    n_glifos = 0
    if buffer:
        try:
            from fontTools.ttLib import TTFont

            embarcada = TTFont(io.BytesIO(buffer), fontNumber=0, lazy=True)
            n_glifos = len(embarcada.getGlyphOrder())
            mapa = _mapa_de_ttfont(embarcada)   # subset com cmap proprio: e o certo
            if mapa:
                return mapa
        except Exception:
            pass

    do_sistema = _mapa_fonte_sistema(_normalizar_nome_fonte(nome_fonte), n_glifos)
    return dict(do_sistema) if do_sistema else {}


def fracao_suspeita(texto: str) -> float:
    """Proporcao de caracteres ilegiveis - o indicador de fonte quebrada."""
    util = "".join(c for c in texto if not c.isspace())
    if not util:
        return 0.0
    return len(PADRAO_SUSPEITO.findall(util)) / len(util)


def _reconstruir_pagina(pagina, documento) -> Optional[str]:
    """Remonta o texto da pagina pelos glyph ids, ignorando o ToUnicode do PDF.

    get_texttrace() devolve os spans em ordem de leitura com (unicode, gid, ...)
    por caractere: o unicode e o que esta quebrado, o gid nao. As quebras de linha
    saem da coordenada vertical do span."""
    try:
        spans = pagina.get_texttrace()
        fontes = pagina.get_fonts()
    except Exception:
        return None

    xref_por_nome: Dict[str, int] = {}
    for info in fontes:
        xref_por_nome.setdefault(_normalizar_nome_fonte(info[3]), info[0])

    linhas: List[str] = []
    atual: List[str] = []
    y_atual: Optional[float] = None
    cache_mapa: Dict[int, Dict[int, int]] = {}

    for span in spans:
        caracteres = span.get("chars") or ()
        if not caracteres:
            continue

        bruto = "".join(chr(c[0]) for c in caracteres)
        texto_span = bruto
        if fracao_suspeita(bruto) >= FRACAO_SUSPEITA_MINIMA:
            xref = xref_por_nome.get(_normalizar_nome_fonte(span.get("font", "")))
            if xref is not None:
                if xref not in cache_mapa:
                    cache_mapa[xref] = _mapa_glifos(documento, xref, span.get("font", ""))
                mapa = cache_mapa[xref]
                if mapa:
                    texto_span = "".join(chr(mapa.get(c[1], c[0])) for c in caracteres)

        y_span = span["bbox"][3]
        if y_atual is None or abs(y_span - y_atual) > TOLERANCIA_LINHA_PT:
            if atual:
                linhas.append("".join(atual))
            atual, y_atual = [texto_span], y_span
        else:
            atual.append(texto_span)

    if atual:
        linhas.append("".join(atual))
    return "\n".join(linhas)


def _texto_pymupdf(caminho: str) -> Optional[TextoPdf]:
    try:
        import pymupdf
    except ImportError:
        return None
    try:
        documento = pymupdf.open(caminho)
    except Exception as erro:
        logger.debug("pymupdf nao abriu %s: %s", caminho, erro)
        return None

    partes: List[str] = []
    reparadas = 0
    try:
        for pagina in documento:
            try:
                texto = pagina.get_text() or ""
            except Exception:
                texto = ""
            if fracao_suspeita(texto) >= FRACAO_SUSPEITA_MINIMA:
                reconstruido = _reconstruir_pagina(pagina, documento)
                if (reconstruido and fracao_suspeita(reconstruido) < fracao_suspeita(texto)
                        and parece_portugues(reconstruido)):
                    texto, reparadas = reconstruido, reparadas + 1
            partes.append(texto)
        total_paginas = documento.page_count
    finally:
        documento.close()

    metodo = "pymupdf_fonte_reparada" if reparadas else "pymupdf"
    return TextoPdf("\n".join(partes), metodo, total_paginas, reparadas)


def _texto_pypdf(caminho: str) -> Optional[TextoPdf]:
    try:
        from pypdf import PdfReader

        leitor = PdfReader(caminho)
        texto = "\n".join(pagina.extract_text() or "" for pagina in leitor.pages)
        return TextoPdf(texto, "pypdf", len(leitor.pages), 0)
    except Exception as erro:
        logger.debug("pypdf nao leu %s: %s", caminho, erro)
        return None


def extrair_texto(caminho: Optional[str]) -> TextoPdf:
    """Melhor texto disponivel do PDF, com a fonte reparada quando necessario.

    Fica com o resultado mais legivel entre PyMuPDF (com reparo) e pypdf, e nao com
    o primeiro que responder: ha PDF em que um dos dois devolve pagina em branco."""
    if not caminho or str(caminho).lower() == "nan":
        return TextoPdf("", "sem_caminho", 0, 0)
    arquivo = Path(str(caminho))
    if not arquivo.exists() or arquivo.stat().st_size == 0:
        return TextoPdf("", "arquivo_ausente", 0, 0)

    candidatos = [r for r in (_texto_pymupdf(str(arquivo)), _texto_pypdf(str(arquivo))) if r]
    if not candidatos:
        return TextoPdf("", "erro_leitura", 0, 0)

    def legibilidade(resultado: TextoPdf) -> Tuple[float, bool]:
        chars_legiveis = len(resultado.texto.strip()) * (1 - fracao_suspeita(resultado.texto))
        return (chars_legiveis, resultado.metodo.startswith("pymupdf"))

    melhor = max(candidatos, key=legibilidade)
    if len(melhor.texto.strip()) < MIN_CHARS_TEXTO_UTIL:
        return melhor._replace(metodo="sem_texto_scan")
    return melhor
