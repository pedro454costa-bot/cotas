/* Painel direito: cadastro, prestadores e demonstracoes do no selecionado.

   Renderiza a partir do CNPJ clicado no grafo - o fundo raiz e so o caso inicial.
   Cada troca de selecao refaz o painel sem recarregar a pagina nem o grafo.
*/

const Painel = (() => {
  const alvo = document.getElementById("painel");
  let aoAbrirAnalise = () => {};

  const e = Formato.escapar;

  function carregando() {
    alvo.innerHTML = '<p class="carregando">Carregando…</p>';
  }

  function erro(mensagem) {
    alvo.innerHTML = `<div class="erro-caixa">${e(mensagem)}</div>`;
  }

  async function mostrar(cnpj) {
    carregando();
    try {
      const [dados, demonstracoes] = await Promise.all([
        API.fundo(cnpj),
        API.demonstracoes(cnpj).catch(() => []),
      ]);
      alvo.innerHTML = montar(dados, demonstracoes);
      ligarCliquesDF(demonstracoes);
    } catch (excecao) {
      if (excecao.status === 404) {
        erro("Este fundo não está no cadastro ativo da CVM. "
           + "Pode ter sido cancelado, liquidado ou pertencer a administrador fora do escopo.");
      } else {
        erro(excecao.message);
      }
    }
  }

  function montar(dados, demonstracoes) {
    const c = dados.cadastro;
    return [
      cabecalho(c, dados.analise_recente, dados.investimentos),
      grupoDemonstracoes(demonstracoes),
      grupoCadastro(c),
      grupoPrestadores(dados.prestadores),
      grupoHistorico(dados.historico_prestadores),
    ].join("");
  }

  function cabecalho(c, analise, investimentos) {
    const selos = [];
    const classe = Formato.classeRisco(c.classificacao_risco);
    selos.push(`<span class="selo ${classe}">${e(Formato.risco(c.classificacao_risco))}</span>`);
    if (investimentos.quantidade > 0) {
      selos.push(`<span class="selo neutro">Fundo investidor · ${investimentos.quantidade}</span>`);
    }
    if (c.fundo_exclusivo) selos.push('<span class="selo neutro">Exclusivo</span>');
    if (c.situacao && !/FUNCIONAMENTO NORMAL/i.test(c.situacao)) {
      selos.push(`<span class="selo medio">${e(c.situacao)}</span>`);
    }

    const motivo = analise && analise.justificativa
      ? `<p class="df-justificativa" style="margin-top:10px">${e(analise.justificativa)}</p>` : "";

    return `
      <div class="painel-cnpj">${e(c.cnpj_formatado)}</div>
      <h2 class="painel-nome">${e(c.denominacao_social)}</h2>
      <div class="painel-classe">${e([c.tp_fundo, c.classe].filter(Boolean).join(" · ") || "—")}</div>
      <div class="selos">${selos.join("")}</div>
      ${motivo}`;
  }

  function grupoDemonstracoes(linhas) {
    if (!linhas.length) {
      return grupo("Demonstrações financeiras",
        '<p class="df-justificativa">Nenhuma demonstração localizada para este fundo.</p>');
    }

    const itens = linhas.slice(0, 8).map((linha, indice) => {
      const classe = Formato.classeRisco(linha.classificacao_risco);
      const analisada = Boolean(linha.classificacao_risco);
      const alerta = linha.divergencia_regex || linha.celula_invalida
        ? '<div class="df-alerta">⚠ Divergência — requer revisão humana</div>' : "";

      // A opiniao do auditor vem antes da justificativa: e o fato do documento,
      // enquanto a justificativa e leitura da IA. Quando a IA nao analisou, cai
      // para o tipo detectado por regex, que continua sendo dado do documento.
      const opiniao = Formato.manifestacao(
        linha.manifestacao || linha.tipo_opiniao_detectado || linha.opiniao_cvm
      );

      return `
        <div class="df-item ${classe}" data-indice="${indice}" role="button" tabindex="0">
          <div class="df-topo">
            <span class="df-ano">${e(linha.ano_referencia)}</span>
            <span class="pilula ${classe}">${e(analisada ? Formato.risco(linha.classificacao_risco) : "Não analisada")}</span>
          </div>
          <div class="df-opiniao">${e(opiniao)}</div>
          ${linha.justificativa ? `<div class="df-justificativa">${e(linha.justificativa)}</div>` : ""}
          ${alerta}
        </div>`;
    }).join("");

    return grupo("Demonstrações financeiras", itens);
  }

  function grupoCadastro(c) {
    const campos = [
      ["Situação", c.situacao],
      ["Condomínio", c.condominio],
      ["Público-alvo", c.publico_alvo],
      ["Constituição", Formato.data(c.data_constituicao)],
      ["Exercício social", c.exercicio_social_fim ? Formato.data(c.exercicio_social_fim) : null],
      ["Patrimônio líquido", c.patrimonio_liquido ? Formato.dinheiro(c.patrimonio_liquido) : null],
      ["Taxa de adm.", c.taxa_administracao ? Formato.percentual(c.taxa_administracao, 2) : null],
    ].filter(([, valor]) => valor);

    const html = campos.map(([rotulo, valor]) =>
      `<div class="linha-dado"><dt>${e(rotulo)}</dt><dd>${e(valor)}</dd></div>`).join("");
    return grupo("Informações cadastrais", `<dl style="margin:0">${html}</dl>`);
  }

  function grupoPrestadores(prestadores) {
    if (!prestadores.length) return "";
    const html = prestadores.map((p) =>
      `<div class="linha-dado"><dt>${e(p.tipo)}</dt><dd>${e(p.nome)}</dd></div>`).join("");
    return grupo("Prestadores de serviço", `<dl style="margin:0">${html}</dl>`);
  }

  function grupoHistorico(historico) {
    if (!historico.length) return "";
    const html = historico.map((h) => `
      <div class="cartao">
        <div class="cartao-topo">
          <strong>${e(Formato.encurtar(h.nome, 42))}</strong>
          ${h.vigente ? '<span class="marca-vigente">atual</span>' : ""}
        </div>
        <div class="cartao-tipo">${e(h.tipo_prestador)}</div>
        <div class="cartao-periodo">${e(Formato.periodo(h.data_inicio, h.data_fim))}</div>
      </div>`).join("");
    return grupo("Histórico de prestadores", html);
  }

  function grupo(titulo, conteudo) {
    return `<div class="grupo"><h3>${e(titulo)}</h3>${conteudo}</div>`;
  }

  function ligarCliquesDF(demonstracoes) {
    alvo.querySelectorAll(".df-item").forEach((elemento) => {
      const abrir = () => aoAbrirAnalise(demonstracoes[Number(elemento.dataset.indice)]);
      elemento.addEventListener("click", abrir);
      elemento.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); abrir(); }
      });
    });
  }

  function vazio() {
    alvo.innerHTML = '<p class="painel-vazio">Selecione um fundo no grafo para ver os detalhes.</p>';
  }

  return {
    mostrar,
    vazio,
    aoAbrirAnalise(callback) { aoAbrirAnalise = callback; },
  };
})();
