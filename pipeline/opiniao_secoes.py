"""Recorte das secoes do Relatorio dos Auditores Independentes.

Objetivo: reduzir ao maximo o texto que vai para a LLM. Em vez de mandar a janela
bruta de 6000 caracteres a partir do cabecalho do relatorio (que carrega capa,
sumario, papel timbrado e ate o inicio de "Principais assuntos de auditoria"),
este modulo recorta so o que interessa:

    trecho_opiniao_secao  -> do titulo da opiniao ate o titulo "Base para ..."
    trecho_base_opiniao   -> do titulo "Base para ..." ate a proxima secao
    trecho_enfase_outros  -> Enfase / Incerteza relevante / Outros assuntos /
                             Valores correspondentes (ver SECOES_RELEVANTES)

Os titulos variam conforme o tipo de opiniao emitida (NBC TA 700/705):

    Opiniao                   / Base para opiniao
    Opiniao com ressalva(s)   / Base para opiniao com ressalva(s)
    Opiniao adversa           / Base para opiniao adversa
    Abstencao de opiniao      / Base para abstencao de opiniao

A versao anterior do pipeline so reconhecia "base (da|de|para) opiniao", entao
relatorios com ressalva/abstencao/adversa nao tinham onde cortar: o campo
trecho_opiniao_secao recebia a janela inteira e o trecho_base_opiniao ficava vazio.

trecho_enfase_outros existe porque o titulo da opiniao nao conta a historia toda:
um fundo pode ter opiniao SEM ressalva e ainda assim carregar um paragrafo de
enfase, uma incerteza de continuidade operacional ou um "Outros assuntos" avisando
que o exercicio anterior foi auditado por outro auditor. Para uma area de Risco
esses casos precisam ser lidos como os modificados.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple, Optional, Tuple

JANELA_MAX_OPINIAO_CHARS = 8000   # teto quando nao se acha o titulo "Base para ..."
JANELA_MAX_BASE_CHARS = 4000      # teto quando nao se acha a proxima secao
DISTANCIA_MAX_TITULO_ATE_BASE = 20000  # o "Base para ..." vem logo depois da opiniao
DISTANCIA_MAX_TITULO_ATE_CORPO = 400   # "Examinamos ..." vem logo apos o titulo

# --- normalizacao que PRESERVA os indices -------------------------------------
# NFKD mudaria o tamanho da string (acento vira caractere separado) e quebraria o
# mapeamento posicao-no-normalizado -> posicao-no-original. Como todo o recorte e
# feito por indice, a normalizacao aqui e 1 caractere por 1 caractere.
_ACENTUADOS = "áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ"
_SEM_ACENTO = "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN"
_TABELA_ACENTOS = str.maketrans(_ACENTUADOS, _SEM_ACENTO)


def normalizar(texto: str) -> str:
    """Minusculas e sem acento, mantendo o mesmo comprimento do original."""
    return texto.translate(_TABELA_ACENTOS).lower()


# --- titulos ------------------------------------------------------------------
# Os PDFs vem com espacos duplos, non-breaking space e as vezes com o titulo entre
# aspas ou seguido de dois-pontos. Pior: o pypdf costuma quebrar palavras no meio
# ("Opiniã o Com Ressalva s", "Op\ninião"), entao os padroes sao montados por
# _flex(), que tolera separador entre quaisquer duas letras da palavra.
_ESPACO = "[ \\t\u00a0\u2007\u202f]"
# Separador entre palavras: "*" e nao "+" porque ha PDFs que grudam tudo
# ("AbstencaoDeOpiniao", "PrincipaisAssuntosDeAuditoria").
_ESP = _ESPACO + "*"
_ASPAS = "[\"“”']?"


def _flex(palavra: str, entre: str) -> str:
    """Regex da palavra tolerando separadores injetados pelo parser do PDF."""
    return entre.join(re.escape(letra) for letra in palavra)


def _montar_padroes(entre: str) -> Tuple[str, str, str]:
    """(titulo da opiniao, titulo da base, abertura do corpo) para um separador."""
    def p(palavra: str) -> str:
        return _flex(palavra, entre)

    _ESP = entre  # entre palavras vale o mesmo separador de dentro da palavra

    qualificador = "(?:{})".format("|".join([
        p("com") + _ESP + p("ressalva") + entre + "s?",
        p("sem") + _ESP + p("ressalva") + entre + "s?",
        p("adversa"), p("modificada"), p("qualificada"),
        p("com") + _ESP + p("abstencao"),
    ]))
    titulo_opiniao = "(?:{}|{})".format(
        p("abstencao") + _ESP + p("de") + _ESP + p("opiniao"),
        p("opiniao") + "(?:" + _ESP + qualificador + ")?",
    )
    titulo_base = (
        p("base") + _ESP + "(?:" + "|".join(p(x) for x in ("para", "de", "da", "do"))
        + ")" + _ESP + titulo_opiniao
    )
    abertura_corpo = "(?:{})".format("|".join([
        p("examinamos"), p("auditamos"), p("revisamos"),
        p("fomos") + _ESP + p("contratados"),
        p("nao") + _ESP + p("expressamos"),
        p("em") + _ESP + p("nossa") + _ESP + p("opiniao"),
        p("nossa") + _ESP + p("auditoria"),
        p("nossas") + _ESP + p("responsabilidades"),
    ]))
    return titulo_opiniao, titulo_base, abertura_corpo


# Na linha propria o separador nao pode incluir \n (senao ^...$ nunca fecha); no
# inline pode, porque e justamente ali que a quebra cai no meio da palavra.
_TITULO_OPINIAO, _TITULO_BASE, _ABERTURA_CORPO = _montar_padroes(_ESPACO + "*")
_TITULO_OPINIAO_NL, _TITULO_BASE_NL, _ABERTURA_CORPO_NL = _montar_padroes(r"\s*")

# Titulo em linha propria: e assim que aparece na esmagadora maioria dos PDFs.
PADRAO_TITULO_OPINIAO_LINHA = re.compile(
    r"^" + _ESPACO + r"*" + _ASPAS + _TITULO_OPINIAO + _ASPAS + _ESPACO + r"*:?" + _ESPACO + r"*$",
    re.IGNORECASE | re.MULTILINE,
)
PADRAO_TITULO_BASE_LINHA = re.compile(
    r"^" + _ESPACO + r"*" + _ASPAS + _TITULO_BASE + _ASPAS + _ESPACO + r"*:?" + _ESPACO + r"*$",
    re.IGNORECASE | re.MULTILINE,
)

# Alguns PDFs grudam o titulo no paragrafo seguinte ("Opiniao\nExaminamos" sai como
# "Opiniao Examinamos") ou entregam a pagina inteira numa linha so. Ai o titulo so
# vale se o corpo do relatorio vier logo em seguida; os lookbehinds barram a mencao
# corriqueira no meio do texto ("... para fundamentar nossa opiniao").
_NAO_E_PROSA = "".join(
    "(?<!{} )".format(termo)
    for termo in ("nossa", "nossas", "uma", "sua", "minha", "de", "da", "na", "a", "e")
)
_ANTES_DO_TITULO = r"(?:^|\n|(?<=[.;:)\]] )|(?<=[a-z0-9] ))"

PADRAO_TITULO_OPINIAO_INLINE = re.compile(
    _ANTES_DO_TITULO + _NAO_E_PROSA + _TITULO_OPINIAO_NL
    + r"\s*[:\-–]?\s*(?=" + _ABERTURA_CORPO_NL + r")",
    re.IGNORECASE,
)
PADRAO_TITULO_BASE_INLINE = re.compile(
    _ANTES_DO_TITULO + _NAO_E_PROSA + _TITULO_BASE_NL
    + r"\s*[:\-–]?\s*(?=[a-z\"“])",
    re.IGNORECASE,
)

# Ha PDF que entrega a pagina inteira sem uma unica quebra de linha, e ai o titulo
# fica colado no que vem antes ("...Sao Paulo SPOpiniao Examinamos as demonstracoes
# contabeis do..."). Sem fronteira a esquerda, nem o padrao de linha nem o inline
# casam. Esta e a ultima tentativa antes de desistir: exige que logo depois do
# titulo venha um verbo que SO aparece na abertura do relatorio - "em nossa
# opiniao" e "nossa auditoria" ficam de fora de proposito, porque casariam com a
# mencao corriqueira no meio do paragrafo e com o inicio da "Base para opiniao".
_ABERTURA_ESTRITA = "(?:{})".format("|".join([
    _flex("examinamos", r"\s*"), _flex("auditamos", r"\s*"), _flex("revisamos", r"\s*"),
    _flex("fomos", r"\s*") + r"\s*" + _flex("contratados", r"\s*"),
    _flex("nao", r"\s*") + r"\s*" + _flex("expressamos", r"\s*"),
]))
PADRAO_TITULO_OPINIAO_COLADO = re.compile(
    _NAO_E_PROSA + _TITULO_OPINIAO_NL + r"\s*[:\-\u2013]?\s*(?=" + _ABERTURA_ESTRITA + r")",
    re.IGNORECASE,
)

# Ha relatorio em que o titulo "Opiniao" simplesmente nao sobrevive a extracao:
# some no cabecalho de uma tabela, vira imagem, ou o PDF cola o paragrafo anterior
# nele de um jeito que nenhuma fronteira reconhece. O corpo, porem, e padronizado
# pela NBC TA 700 e comeca sempre da mesma forma. Quando nada mais casa, o recorte
# ancora aqui - o tipo da opiniao sai do titulo "Base para ...", que costuma
# sobreviver porque vem em linha propria.
PADRAO_ANCORA_CORPO = re.compile(
    r"(?:{})".format("|".join([
        _flex("examinamos", r"\s*") + r"\s+(?:as|o)\s",
        _flex("auditamos", r"\s*") + r"\s+(?:as|o)\s",
        _flex("fomos", r"\s*") + r"\s+" + _flex("contratados", r"\s*"),
        _flex("nao", r"\s*") + r"\s+" + _flex("expressamos", r"\s*"),
    ])),
    re.IGNORECASE,
)

# Confirma que o titulo achado abre mesmo o relatorio (e nao e uma citacao no meio
# do paragrafo, tipo: ... descrito na secao "Base para opiniao com ressalva", ...)
PADRAO_ABERTURA_CORPO = re.compile(_ABERTURA_CORPO_NL, re.IGNORECASE)

# --- demais secoes do relatorio -----------------------------------------------
# Uma unica fonte de verdade para os cabecalhos que vem DEPOIS da opiniao. Serve
# para duas coisas: saber onde termina a "Base para ..." (qualquer um deles) e
# saber onde comecam as secoes que a area de Risco precisa ler mesmo quando a
# opiniao esta limpa (ver SECOES_RELEVANTES).

# Complemento do titulo. Sem pontuacao de prosa e curto de proposito: o pypdf
# quebra os paragrafos em linhas de ~80 caracteres, e uma linha de texto corrido
# que por acaso comece com a palavra do cabecalho passaria por cabecalho.
_COMPLEMENTO = r"[^\n.;,!?]{0,60}"

_CORPO_SECOES = {
    "paa": r"principais" + _ESP + r"assuntos" + _ESP + r"de" + _ESP + r"auditoria" + _COMPLEMENTO,
    # "Enfase", "Enfases", "Paragrafo de enfase", "Enfase - Reapresentacao ..."
    "enfase": (
        r"(?:paragrafos?" + _ESP + r"de" + _ESP + r")?enfases?"
        r"(?:" + _ESPACO + r"*[-–:]" + _COMPLEMENTO + r")?"
    ),
    # O cabecalho da NBC TA 570 e "Incerteza relevante relacionada com a
    # continuidade operacional". Sem restringir o complemento, casaria com a linha
    # quebrada do texto-padrao das Responsabilidades ("... se existe / incerteza
    # relevante em relacao a eventos ou condicoes que possam levantar duvida ...").
    "incerteza": (
        r"incerteza" + _ESP + r"(?:relevante|significativa)"
        r"(?:" + _ESPACO + r"*(?:relacionada|relativa|quanto|sobre|com|referente)"
        + _COMPLEMENTO + r")?"
    ),
    "outros_assuntos": r"outros?" + _ESP + r"assuntos?" + r"[^\n.;,!?]{0,30}",
    "valores_correspondentes": (
        r"(?:"
        r"(?:auditoria" + _ESP + r"dos" + _ESP + r")?valores" + _ESP + r"correspondentes|"
        r"reapresentacao" + _ESP + r"dos" + _ESP + r"valores|"
        r"demonstracoes" + _ESP + r"financeiras" + _ESP + r"(?:do" + _ESP + r")?exercicio"
        + _ESP + r"anterior"
        r")" + _COMPLEMENTO
    ),
    "outras_informacoes": r"outras" + _ESP + r"informacoes" + _COMPLEMENTO,
    "responsabilidades": (
        r"(?:"
        r"responsabilidades?" + _ESP + r"d[ao]s?" + _ESP
        + r"(?:administracao|auditor|governanca|administrador|gestao)|"
        r"responsaveis" + _ESP + r"pela" + _ESP + r"governanca"
        r")" + _COMPLEMENTO
    ),
}

PADRAO_SECAO_CONHECIDA = re.compile(
    r"^" + _ESPACO + r"*(?:"
    + "|".join("(?P<{}>{})".format(nome, corpo) for nome, corpo in _CORPO_SECOES.items())
    # cada secao ja traz o proprio complemento; aqui so fecha a linha
    + r")" + _ESPACO + r"*:?" + _ESPACO + r"*$",
    re.IGNORECASE | re.MULTILINE,
)
# O fim da "Base para ..." e o inicio de qualquer outra secao conhecida.
PADRAO_PROXIMA_SECAO = PADRAO_SECAO_CONHECIDA

# Secoes que, sozinhas, ja justificam a leitura do analista: um fundo pode ter
# opiniao SEM ressalva e mesmo assim carregar um paragrafo de enfase, uma
# incerteza de continuidade operacional, um "Outros assuntos" dizendo que o
# exercicio anterior foi auditado por outro auditor, ou uma reapresentacao de
# valores. Nada disso aparece no titulo da opiniao.
# Nem toda ausencia de opiniao e falha de leitura. A Resolucao CVM 175 (art. 65,
# paragrafo unico) dispensa o relatorio do auditor no primeiro exercicio de alguns
# fundos, e ha DF que declara isso em texto. Sem separar os dois casos, um fundo
# legitimamente dispensado fica para sempre na fila de revisao manual.
PADRAO_DISPENSA_RELATORIO = re.compile(
    r"(?:dispensad[ao]s?[^.]{0,80}relatorio d[oe]s? auditor"
    r"|sem relatorio d[oe]s? auditores independentes"
    r"|dispensad[ao]s?[^.]{0,60}auditoria independente"
    r"|nao (?:foram|sao) auditad[ao]s)",
    re.IGNORECASE,
)

SECOES_RELEVANTES = ("enfase", "incerteza", "outros_assuntos", "valores_correspondentes")

JANELA_VARREDURA_SECOES = 40000  # o relatorio do auditor nao passa disso; o resto do PDF sao as notas
MAX_CHARS_POR_SECAO_ADICIONAL = 2500
MAX_CHARS_SECOES_ADICIONAIS = 6000

# --- limpeza do texto ---------------------------------------------------------
# Papel timbrado, rodape e numero de pagina entram no meio do recorte porque o
# pypdf le a pagina inteira. Sao linhas previsiveis e puro ruido para a LLM.
PADROES_RUIDO_LINHA = re.compile(
    r"^\s*(?:"
    r"\d{1,3}|"
    r"p[aá]gina\s+\d+(?:\s+de\s+\d+)?|"
    r".{0,90}(?:firma[- ]membro|member\s+firm|empresa[- ]membro|"
    r"limited\s+by\s+guarantee|international\s+limited|global\s+limited|"
    r"sociedade\s+simples\s+brasileira|brazilian\s+limited\s+liability|"
    r"independent\s+member\s+firms|docusign\s+envelope).{0,90}|"
    r"\(\s*administrad[oa]\s+pel[ao].{0,120}\)|"  # cabecalho de pagina repetido
    r"(?:tel(?:efone)?|fax|caixa\s+postal|cep)\b.{0,70}|"
    r"(?:www\.|https?://)\S+|"
    r"\S+@\S+\.\S+|"
    r"[a-z]{2,}\.com(?:\.br)?"
    r")\s*$",
    re.IGNORECASE,
)

# XML - e por extensao o .xlsx - so aceita tab, LF e CR como caracteres de
# controle; qualquer outro faz o openpyxl estourar IllegalCharacterError na hora
# de gravar. Um PDF com fonte corrompida ou mal mapeada (glifo -> codepoint
# errado) injeta esses bytes no meio do texto extraido. Nao e problema de
# encoding nosso: e sujeira do documento de origem, entao so descartamos.
PADRAO_CARACTERE_ILEGAL_XML = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f\ufdd0-\ufdef\ufffe\uffff]"
)


def limpar_trecho(trecho: str) -> str:
    """Tira papel timbrado/rodape/numero de pagina e normaliza o espacamento."""
    trecho = PADRAO_CARACTERE_ILEGAL_XML.sub("", trecho)
    linhas_limpas = []
    for linha in trecho.splitlines():
        linha = linha.replace("\u00a0", " ").strip()
        if not linha or PADROES_RUIDO_LINHA.match(linha):
            continue
        linhas_limpas.append(re.sub(r"\s{2,}", " ", linha))
    return "\n".join(linhas_limpas).strip()


def _limpar_titulo(bruto: str) -> Optional[str]:
    """Titulo em uma linha so, sem aspas/dois-pontos e sem caractere ilegal de XML."""
    titulo = PADRAO_CARACTERE_ILEGAL_XML.sub("", bruto)
    return re.sub(r"\s+", " ", titulo).strip().strip("\"“”':") or None


def classificar_tipo_opiniao(titulo: Optional[str]) -> Optional[str]:
    """Deriva o tipo de opiniao do proprio titulo recortado (NBC TA 700/705)."""
    if not titulo:
        return None
    alvo = re.sub(r"\s+", " ", normalizar(titulo))
    if "abstenc" in alvo:
        return "ABSTENCAO"
    if "adversa" in alvo:
        return "ADVERSA"
    if "ressalva" in alvo:
        return "SEM_RESSALVA" if re.search(r"sem ressalva", alvo) else "COM_RESSALVA"
    if "modificada" in alvo:
        return "MODIFICADA"
    return "SEM_RESSALVA"


class SecoesOpiniao(NamedTuple):
    trecho_opiniao_secao: Optional[str]
    trecho_base_opiniao: Optional[str]
    trecho_enfase_outros: Optional[str]
    secoes_adicionais: Optional[str]
    titulo_opiniao: Optional[str]
    titulo_base: Optional[str]
    tipo_opiniao_detectado: Optional[str]
    metodo_recorte: str


SECOES_VAZIAS = SecoesOpiniao(None, None, None, None, None, None, None, "")


def extrair_secoes_adicionais(texto: str, alvo: str, inicio: int) -> Tuple[Optional[str], Optional[str]]:
    """Recorta Enfase / Incerteza / Outros assuntos / Valores correspondentes.

    Diferente da opiniao e da base, essas secoes nao sao contiguas: a enfase vem
    logo apos a base, mas "Outros assuntos" costuma vir depois dos Principais
    Assuntos de Auditoria ou ate depois das Responsabilidades. Entao a varredura
    mapeia TODOS os cabecalhos conhecidos e junta so os blocos relevantes, cada um
    terminando no cabecalho seguinte."""
    limite = min(len(alvo), inicio + JANELA_VARREDURA_SECOES)
    cabecalhos = [m for m in PADRAO_SECAO_CONHECIDA.finditer(alvo, inicio) if m.start() < limite]
    if not cabecalhos:
        return None, None

    blocos, nomes = [], []
    for posicao, cabecalho in enumerate(cabecalhos):
        if cabecalho.lastgroup not in SECOES_RELEVANTES:
            continue
        fim = cabecalhos[posicao + 1].start() if posicao + 1 < len(cabecalhos) else limite
        bloco = limpar_trecho(texto[cabecalho.start() : min(fim, cabecalho.start() + MAX_CHARS_POR_SECAO_ADICIONAL)])
        if not bloco:
            continue
        blocos.append(bloco)
        if cabecalho.lastgroup not in nomes:
            nomes.append(cabecalho.lastgroup)

    if not blocos:
        return None, None
    return "\n\n".join(blocos)[:MAX_CHARS_SECOES_ADICIONAIS].strip(), ", ".join(nomes)


def _achar_titulo_opiniao(alvo: str, inicio_busca: int = 0):
    """Primeiro titulo de opiniao que abre um corpo de relatorio de verdade.

    Titulo em linha propria seguido, em poucos caracteres, de "Examinamos"/
    "Fomos contratados"/"Nao expressamos" e o inicio do relatorio. Titulo em linha
    propria SEM isso por perto costuma ser entrada de sumario."""
    candidatos = list(PADRAO_TITULO_OPINIAO_LINHA.finditer(alvo, inicio_busca))
    for match in candidatos:
        janela = alvo[match.end() : match.end() + DISTANCIA_MAX_TITULO_ATE_CORPO]
        if PADRAO_ABERTURA_CORPO.search(janela):
            return match, "titulo_em_linha"

    match_inline = PADRAO_TITULO_OPINIAO_INLINE.search(alvo, inicio_busca)
    if match_inline:
        return match_inline, "titulo_inline"

    match_colado = PADRAO_TITULO_OPINIAO_COLADO.search(alvo, inicio_busca)
    if match_colado:
        return match_colado, "titulo_colado"

    if candidatos:  # sem corpo reconhecivel: fica com o ultimo (o do corpo, nao o do sumario)
        return candidatos[-1], "titulo_em_linha_sem_corpo"
    return None, None


def _achar_titulo_base(alvo: str, inicio_busca: int):
    limite = inicio_busca + DISTANCIA_MAX_TITULO_ATE_BASE
    for padrao in (PADRAO_TITULO_BASE_LINHA, PADRAO_TITULO_BASE_INLINE):
        match = padrao.search(alvo, inicio_busca)
        if match is not None and match.start() <= limite:
            return match
    return None


def _pular_quebras(texto: str, posicao: int) -> int:
    while posicao < len(texto) and texto[posicao] in "\r\n \t":
        posicao += 1
    return posicao


def extrair_secoes(texto: str) -> SecoesOpiniao:
    """Recorta as secoes "Opiniao" e "Base para ..." do texto do relatorio."""
    if not texto or not texto.strip():
        return SECOES_VAZIAS._replace(metodo_recorte="texto_vazio")

    alvo = normalizar(texto)

    match_opiniao, metodo = _achar_titulo_opiniao(alvo)
    if match_opiniao is None:
        match_opiniao = PADRAO_ANCORA_CORPO.search(alvo)
        if match_opiniao is None:
            if PADRAO_DISPENSA_RELATORIO.search(alvo):
                return SECOES_VAZIAS._replace(metodo_recorte="dispensado_sem_relatorio")
            return SECOES_VAZIAS._replace(metodo_recorte="titulo_opiniao_nao_localizado")
        metodo = "ancora_corpo"   # sem titulo: o tipo vem do "Base para ..."

    # o match inline comeca no \n anterior; nao arrasta a quebra para o recorte
    inicio_opiniao = _pular_quebras(texto, match_opiniao.start())
    match_base = _achar_titulo_base(alvo, match_opiniao.end())

    if match_base is not None:
        inicio_base = _pular_quebras(texto, match_base.start())
        bruto_opiniao = texto[inicio_opiniao:inicio_base]

        match_proxima = PADRAO_PROXIMA_SECAO.search(alvo, match_base.end())
        fim_base = (
            match_proxima.start()
            if match_proxima and match_proxima.start() - inicio_base <= JANELA_MAX_BASE_CHARS
            else inicio_base + JANELA_MAX_BASE_CHARS
        )
        bruto_base = texto[inicio_base:fim_base]
        inicio_adicionais = match_base.end()
        metodo_recorte = metodo + "+base"
    else:
        # Sem "Base para ...": corta a opiniao na proxima secao conhecida.
        match_proxima = PADRAO_PROXIMA_SECAO.search(alvo, match_opiniao.end())
        fim_opiniao = (
            match_proxima.start()
            if match_proxima and match_proxima.start() - inicio_opiniao <= JANELA_MAX_OPINIAO_CHARS
            else inicio_opiniao + JANELA_MAX_OPINIAO_CHARS
        )
        bruto_opiniao = texto[inicio_opiniao:fim_opiniao]
        bruto_base = None
        inicio_adicionais = match_opiniao.end()
        metodo_recorte = metodo + "+sem_base"

    titulo_opiniao = (
        None if metodo == "ancora_corpo"
        else _limpar_titulo(texto[inicio_opiniao : match_opiniao.end()])
    )
    titulo_base = (
        _limpar_titulo(texto[_pular_quebras(texto, match_base.start()) : match_base.end()])
        if match_base is not None
        else None
    )

    trecho_adicionais, nomes_adicionais = extrair_secoes_adicionais(texto, alvo, inicio_adicionais)

    return SecoesOpiniao(
        trecho_opiniao_secao=limpar_trecho(bruto_opiniao) or None,
        trecho_base_opiniao=(limpar_trecho(bruto_base) or None) if bruto_base else None,
        trecho_enfase_outros=trecho_adicionais,
        secoes_adicionais=nomes_adicionais,
        titulo_opiniao=titulo_opiniao,
        titulo_base=titulo_base,
        tipo_opiniao_detectado=classificar_tipo_opiniao(titulo_opiniao or titulo_base),
        metodo_recorte=metodo_recorte,
    )


# --- Reaproveitamento do recorte a partir do PDF ja em cache ---------------
# Usado tanto pelo reprocessamento de um Excel antigo
# (08_sob_demanda_recortar_secoes_excel.py) quanto pelo export direto do banco
# (09_sob_demanda_exportar_base_opiniao.py). Fica aqui, junto de extrair_secoes,
# para as duas rotas classificarem exatamente do mesmo jeito.

METODOS_SEM_RECORTE = {"texto_vazio", "titulo_opiniao_nao_localizado", "dispensado_sem_relatorio"}


def remontar_janela(trecho_opiniao_secao: Optional[str], trecho_base_opiniao: Optional[str]) -> str:
    """Junta de volta as duas colunas antigas: elas sao fatias contiguas da mesma
    janela (a versao antiga cortava em "Base para opiniao" e guardava 3000 chars a
    partir dali), entao concatenar reconstroi o texto que existia. E o fallback de
    quando o PDF nao esta mais no cache."""
    partes = [str(valor or "").strip() for valor in (trecho_opiniao_secao, trecho_base_opiniao)]
    return "\n".join(p for p in partes if p and p.lower() != "nan")


def recortar_do_pdf(caminho: Optional[str]) -> Optional["SecoesOpiniao"]:
    """Le o PDF do cache local e recorta a partir do texto completo.

    Retorna None quando nao da para aproveitar (sem caminho, arquivo ausente/vazio,
    PDF corrompido ou sem camada de texto) - cabe a quem chama cair no fallback da
    janela antiga. Escrita para rodar em processo separado: nao toca no banco e so
    recebe/devolve tipos simples."""
    if not caminho or str(caminho).lower() == "nan":
        return None
    arquivo = Path(str(caminho))
    if not arquivo.exists() or arquivo.stat().st_size == 0:
        return None
    try:
        # pdf_texto escolhe entre PyMuPDF e pypdf e conserta a fonte quando o PDF
        # vem com ToUnicode quebrado - era o que colocava 1.302 documentos legiveis
        # na fila de revisao manual.
        from pipeline.pdf_texto import extrair_texto

        texto = extrair_texto(str(arquivo)).texto
    except Exception:  # PDF corrompido/criptografado nao pode derrubar o lote
        return None
    if not texto.strip():
        return None
    secoes = extrair_secoes(texto)
    if secoes.metodo_recorte in METODOS_SEM_RECORTE:
        return None
    return secoes._replace(metodo_recorte=secoes.metodo_recorte + "+pdf")


# A CVM ja publica a opiniao classificada para parte dos documentos (campo
# opiniao_estruturada, vindo de DFIN_FII e das cargas manuais). Quando existe, ela
# vale mais do que qualquer heuristica nossa - e resolve inclusive os casos em que
# nao ha PDF nenhum para ler, que e o que acontece com todo o DFIN_FII.
_TIPOS_CVM = (
    ("abstenc", "ABSTENCAO"),
    ("advers", "ADVERSA"),
    ("com ressalva", "COM_RESSALVA"),
    ("sem ressalva", "SEM_RESSALVA"),
)


def classificar_opiniao_cvm(valor: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(tipo, secoes_adicionais) a partir do texto estruturado da CVM.

    "Sem ressalva e com enfase" e o caso que justifica o cuidado com a negacao:
    a string carrega as duas palavras, e so o "com" distingue do "sem enfase"."""
    if not valor or str(valor).lower() == "nan":
        return None, None
    alvo = re.sub(r"\s+", " ", normalizar(str(valor)))
    if "dispensad" in alvo:
        return None, None
    tipo = next((codigo for chave, codigo in _TIPOS_CVM if chave in alvo), None)
    adicionais = "enfase" if re.search(r"com enfase", alvo) else None
    return tipo, adicionais


def complementar_com_cvm(secoes: "SecoesOpiniao", opiniao_cvm: Optional[str]) -> "SecoesOpiniao":
    """Preenche o que a leitura do PDF nao conseguiu, sem sobrescrever o que ela achou."""
    if secoes.tipo_opiniao_detectado:
        return secoes
    if opiniao_cvm and "dispensad" in normalizar(str(opiniao_cvm)):
        return secoes._replace(metodo_recorte="dispensado_sem_relatorio")
    tipo, adicionais = classificar_opiniao_cvm(opiniao_cvm)
    if not tipo:
        return secoes
    return secoes._replace(
        tipo_opiniao_detectado=tipo,
        secoes_adicionais=secoes.secoes_adicionais or adicionais,
        metodo_recorte=(secoes.metodo_recorte or "") + "+classificacao_cvm",
    )


def classificar_triagem(secoes: "SecoesOpiniao") -> Tuple[str, str]:
    """Decide se o documento precisa mesmo passar por LLM.

    Opiniao sem ressalva e texto normativo identico em milhares de documentos - nao
    ha o que resumir. O que justifica a leitura e a opiniao ser modificada OU haver
    enfase / incerteza / outros assuntos, que o titulo da opiniao nao revela."""
    if secoes.metodo_recorte == "dispensado_sem_relatorio":
        return "Nao", "dispensado_sem_relatorio_auditor"
    if secoes.metodo_recorte in METODOS_SEM_RECORTE and not secoes.tipo_opiniao_detectado:
        return "Nao", "sem_texto_revisar_manual"

    # Recorte pela ancora do corpo, sem titulo nem "Base para ...": o trecho existe
    # mas nada no texto diz de que tipo e a opiniao. E exatamente o caso em que a
    # LLM resolve - marcar como limpo aqui seria esconder um documento nao lido.
    if not secoes.tipo_opiniao_detectado:
        return "Sim", "tipo_opiniao_nao_identificado"

    motivos = []
    if secoes.tipo_opiniao_detectado and secoes.tipo_opiniao_detectado != "SEM_RESSALVA":
        motivos.append("opiniao_" + secoes.tipo_opiniao_detectado.lower())
    if secoes.secoes_adicionais:
        motivos.append(secoes.secoes_adicionais)

    return ("Sim", " + ".join(motivos)) if motivos else ("Nao", "opiniao_limpa_sem_apontamentos")
