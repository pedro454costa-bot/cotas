/* Orquestracao: abas, busca, carga do fundo e a gaveta de analise. */

// Marcador de versao: aparece no console assim que a pagina carrega. Serve para
// saber, sem adivinhacao, se o navegador esta executando o codigo atual ou uma
// copia velha em cache - erro que ja custou tempo neste projeto.
const VERSAO_APP = "10";
console.log(`%cRisk Map · frontend v${VERSAO_APP}`, "color:#7A1128;font-weight:700");
window.RISKMAP_VERSAO = VERSAO_APP;

(() => {
  const e = Formato.escapar;

  const el = {
    busca: document.getElementById("busca"),
    sugestoes: document.getElementById("sugestoes"),
    analisar: document.getElementById("btn-analisar"),
    exemplos: document.getElementById("exemplos"),
    veredito: document.getElementById("veredito"),
    seloVeredito: document.getElementById("selo-veredito"),
    vereditoMensagem: document.getElementById("veredito-mensagem"),
    vereditoContadores: document.getElementById("veredito-contadores"),
    palco: document.getElementById("palco"),
    grafo: document.getElementById("grafo"),
    grafoVazio: document.getElementById("grafo-vazio"),
    estadoInicial: document.getElementById("estado-inicial"),
    identidade: document.getElementById("identidade"),
    gaveta: document.getElementById("gaveta"),
    gavetaFundo: document.getElementById("gaveta-fundo"),
  };

  let cnpjAtual = null;
  let bloqueados = new Set();
  let marcado = -1;
  let temporizador = null;

  /* ------------------------------------------------------------- abas -- */

  function trocarVista(nome) {
    document.querySelectorAll(".aba").forEach((aba) =>
      aba.classList.toggle("ativa", aba.dataset.vista === nome));
    document.querySelectorAll(".vista").forEach((vista) =>
      vista.classList.toggle("ativa", vista.id === `vista-${nome}`));

    if (nome === "monitoramento") Monitoramento.carregar().catch(mostrarFalha);
    if (nome === "lista") Monitoramento.carregarListaNegativa().catch(mostrarFalha);
  }

  document.getElementById("abas").addEventListener("click", (ev) => {
    const aba = ev.target.closest(".aba");
    if (aba) trocarVista(aba.dataset.vista);
  });

  /* ------------------------------------------------------------ busca -- */

  async function sugerir(termo) {
    if (termo.trim().length < 3) return esconderSugestoes();
    try {
      const resultados = await API.buscar(termo);
      if (!resultados.length) return esconderSugestoes();

      el.sugestoes.innerHTML = resultados.map((r, i) => `
        <li data-cnpj="${r.cnpj}" data-i="${i}">
          <strong>${e(Formato.encurtar(r.nome, 58))}</strong>
          <span>${e(r.cnpj_formatado)}</span>
          <em> · ${e(r.administrador || "—")}</em>
        </li>`).join("");
      el.sugestoes.hidden = false;
      marcado = -1;
    } catch (_) {
      esconderSugestoes();
    }
  }

  function esconderSugestoes() {
    el.sugestoes.hidden = true;
    el.sugestoes.innerHTML = "";
    marcado = -1;
  }

  el.busca.addEventListener("input", (ev) => {
    clearTimeout(temporizador);
    const termo = ev.target.value;
    temporizador = setTimeout(() => sugerir(termo), 220);
  });

  el.busca.addEventListener("keydown", (ev) => {
    const itens = [...el.sugestoes.querySelectorAll("li")];
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      if (!itens.length) return;
      ev.preventDefault();
      marcado = (marcado + (ev.key === "ArrowDown" ? 1 : -1) + itens.length) % itens.length;
      itens.forEach((li, i) => li.classList.toggle("marcado", i === marcado));
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      if (marcado >= 0 && itens[marcado]) selecionar(itens[marcado].dataset.cnpj);
      else analisarDigitado();
    } else if (ev.key === "Escape") {
      esconderSugestoes();
    }
  });

  el.sugestoes.addEventListener("click", (ev) => {
    const item = ev.target.closest("li");
    if (item) selecionar(item.dataset.cnpj);
  });

  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".campo-busca")) esconderSugestoes();
  });

  function analisarDigitado() {
    const digitos = el.busca.value.replace(/\D/g, "");
    if (digitos.length === 14) selecionar(digitos);
    else sugerir(el.busca.value);
  }

  el.analisar.addEventListener("click", analisarDigitado);

  /* ------------------------------------------------- carga de um fundo -- */

  async function selecionar(cnpj) {
    esconderSugestoes();
    cnpjAtual = cnpj;
    el.busca.value = Formato.cnpj(cnpj);
    el.estadoInicial.hidden = true;
    el.palco.hidden = false;
    // O ceu sai de cena: nao faz sentido animar canvas escondido.
    Constelacao.parar();
    el.analisar.disabled = true;

    Painel.mostrar(cnpj);

    try {
      const risco = await API.riscoCadeia(cnpj);
      bloqueados = new Set(risco.criticos.filter((c) => c.na_lista_negativa).map((c) => c.cnpj));
      mostrarVeredito(risco);
    } catch (_) {
      el.veredito.hidden = true;
    }

    // Buscar e desenhar sao dois try separados de proposito: falha de desenho
    // nao pode ser reportada como "fundo sem carteira". Foi o que aconteceu com
    // o bundle errado do vis-network - o grafo quebrava e a tela dizia que o
    // fundo nao tinha posicoes, mandando o usuario investigar o dado errado.
    let dados = null;
    try {
      dados = await API.grafo(cnpj);
    } catch (excecao) {
      Grafo.destruir();
      mostrarGrafoVazio(
        excecao.status === 404 ? "Sem posições na CDA" : "Não foi possível carregar o grafo",
        excecao.status === 404
          ? "Este fundo não possui carteira informada na competência disponível."
          : excecao.message
      );
      el.analisar.disabled = false;
      return;
    }

    try {
      el.grafoVazio.hidden = true;
      Grafo.desenhar(el.grafo, dados, bloqueados);
      atualizarIdentidade(dados.nos.find((n) => n.eh_raiz));
    } catch (excecao) {
      console.error("Falha ao desenhar o grafo:", excecao);
      Grafo.destruir();
      mostrarGrafoVazio(
        "Erro ao desenhar o grafo",
        `${dados.nos.length} fundos foram carregados, mas a renderização falhou: ${excecao.message}`
      );
    } finally {
      el.analisar.disabled = false;
    }
  }

  function mostrarVeredito(risco) {
    const classe = { VEDADO: "vedado", ATENCAO: "atencao", LIBERADO: "liberado" }[risco.veredito];
    const rotulo = { VEDADO: "VEDAR INVESTIMENTO", ATENCAO: "ANALISAR COM ATENÇÃO", LIBERADO: "SEM RESTRIÇÃO" }[risco.veredito];

    el.veredito.className = `veredito ${classe}`;
    el.seloVeredito.className = `selo-veredito ${classe}`;
    el.seloVeredito.textContent = rotulo;
    el.vereditoMensagem.textContent = risco.mensagem;

    const c = risco.contadores;
    el.vereditoContadores.innerHTML = [
      contador(c.lista_negativa, "Lista Neg.", c.lista_negativa > 0),
      contador(c.opiniao_modificada, "Op. Modif.", c.opiniao_modificada > 0),
      contador(c.fundos_na_cadeia, "Fundos", false),
    ].join("");
    el.veredito.hidden = false;
  }

  function mostrarGrafoVazio(titulo, detalhe) {
    el.grafoVazio.innerHTML = `<strong>${e(titulo)}</strong><p>${e(detalhe)}</p>`;
    el.grafoVazio.hidden = false;
  }

  function contador(valor, rotulo, alerta) {
    return `<div class="${alerta ? "alerta" : ""}"><b>${valor}</b><span>${e(rotulo)}</span></div>`;
  }

  function atualizarIdentidade(raiz) {
    if (!raiz) return;
    el.identidade.hidden = false;
    document.getElementById("identidade-nome").textContent = Formato.encurtar(raiz.nome || "", 46);
    document.getElementById("identidade-detalhe").textContent =
      `${Formato.cnpj(raiz.cnpj)} · ${Formato.encurtar(raiz.administrador || "—", 26)}`;
    document.getElementById("identidade-sigla").textContent = Formato.sigla(raiz.nome);
  }

  Grafo.aoSelecionar((no) => Painel.mostrar(no.cnpj));
  Grafo.aoDuploClicar((no) => selecionar(no.cnpj));

  /* ----------------------------------------------------------- gaveta -- */

  function abrirGaveta(analise) {
    if (!analise) return;
    const classe = Formato.classeRisco(analise.classificacao_risco);
    const alerta = analise.divergencia_regex || analise.celula_invalida
      ? `<div class="erro-caixa">Esta análise foi marcada para revisão humana:
         ${analise.divergencia_regex ? "a leitura da IA diverge da classificação automática do documento." : ""}
         ${analise.celula_invalida ? "a combinação de manifestação e risco está fora da matriz." : ""}</div>`
      : "";

    const modelo = analise.modelo || "modelo de linguagem";
    const quando = analise.atualizado_em ? Formato.data(analise.atualizado_em) : null;

    el.gaveta.innerHTML = `
      <div class="gaveta-topo">
        <h2>${e(analise.nome || Formato.cnpj(analise.fundo_cnpj))}</h2>
        <button class="fechar" aria-label="Fechar">×</button>
      </div>
      <div class="painel-cnpj">${e(Formato.cnpj(analise.fundo_cnpj))} · exercício ${e(analise.ano_referencia)}</div>

      <div class="grupo">
        <h3>Opinião do auditor</h3>
        <div class="opiniao-destaque">${e(Formato.manifestacao(analise.manifestacao))}</div>
      </div>

      <div class="faixa-ia">
        <span class="selo-ia">✦ Gerado por IA</span>
        <p>A classificação de risco e os textos abaixo foram produzidos por
           ${e(modelo)} a partir do relatório do auditor${quando ? `, em ${e(quando)}` : ""}.
           Não substituem a leitura do documento original.</p>
      </div>

      <div class="selos">
        <span class="selo ${classe}">${e(Formato.risco(analise.classificacao_risco))}</span>
        <span class="selo neutro">${e(analise.status_analista || "PENDENTE")}</span>
      </div>
      ${alerta}
      <div class="bloco-analise">
        <h4>Justificativa da classificação <span class="marca-ia">IA</span></h4>
        <p class="citacao">${e(analise.justificativa || "—")}</p>
      </div>
      <div class="bloco-analise">
        <h4>Análise de impacto <span class="marca-ia">IA</span></h4>
        <p>${e(analise.impacto || "Sem análise de impacto registrada.")}</p>
      </div>`;

    el.gaveta.hidden = false;
    el.gavetaFundo.hidden = false;
    el.gaveta.querySelector(".fechar").addEventListener("click", fecharGaveta);
  }

  function fecharGaveta() {
    el.gaveta.hidden = true;
    el.gavetaFundo.hidden = true;
  }

  el.gavetaFundo.addEventListener("click", fecharGaveta);
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") fecharGaveta(); });

  Painel.aoAbrirAnalise(abrirGaveta);
  Monitoramento.aoAbrirAnalise(abrirGaveta);

  /* ------------------------------------------------------------ inicio -- */

  function mostrarFalha(excecao) {
    console.error(excecao);
  }

  async function iniciarConstelacao() {
    try {
      const total = await Constelacao.iniciar(
        document.getElementById("constelacao"),
        (cnpj) => selecionar(cnpj)
      );
      document.getElementById("ceu-legenda").textContent =
        `${total.toLocaleString("pt-BR")} fundos · agrupados por classe`;
    } catch (excecao) {
      document.getElementById("ceu-legenda").textContent = "Não foi possível carregar o universo de fundos.";
      mostrarFalha(excecao);
    }
  }

  async function iniciar() {
    Painel.vazio();
    iniciarConstelacao();
    Monitoramento.iniciar();
    Monitoramento.carregarIndicadores().catch(mostrarFalha);
    API.listaNegativa()
      .then((l) => { document.getElementById("badge-lista").textContent = l.length; })
      .catch(mostrarFalha);

    try {
      const exemplos = await API.exemplos();
      if (!exemplos.length) return;
      el.exemplos.innerHTML = "<b>Exemplos:</b> " + exemplos
        .map((x) => `<a href="#" data-cnpj="${x.cnpj}">${Formato.cnpj(x.cnpj)}</a>`)
        .join(" · ");
      el.exemplos.addEventListener("click", (ev) => {
        const link = ev.target.closest("a");
        if (link) { ev.preventDefault(); selecionar(link.dataset.cnpj); }
      });
    } catch (excecao) {
      mostrarFalha(excecao);
    }
  }

  iniciar();
})();
