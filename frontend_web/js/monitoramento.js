/* Tela 2 - fila de trabalho do analista, e a Lista Negativa. */

const Monitoramento = (() => {
  const e = Formato.escapar;
  const corpo = document.querySelector("#tabela-monitoramento tbody");
  const vazio = document.getElementById("monitoramento-vazio");
  const cards = document.getElementById("cards-indicadores");

  const STATUS = ["PENDENTE", "QUESTIONADO", "ESCALADO", "RESOLVIDO"];
  let aoAbrirAnalise = () => {};
  let ultimaLista = [];
  let temporizador = null;

  function filtros() {
    const valores = {
      administrador: document.getElementById("f-administrador").value.trim(),
      risco: document.getElementById("f-risco").value,
      status: document.getElementById("f-status").value,
      apenas_revisao: document.getElementById("f-revisao").checked,
    };
    // Parametro vazio vira filtro vazio no backend; melhor nem enviar.
    Object.keys(valores).forEach((k) => {
      if (valores[k] === "" || valores[k] === false) delete valores[k];
    });
    return valores;
  }

  async function carregarIndicadores() {
    const dados = await API.indicadores();
    const risco = dados.por_risco || {};
    const status = dados.por_status || {};

    cards.innerHTML = [
      card("Análises", dados.total, ""),
      card("Alto risco", risco.ALTO || 0, "alto"),
      card("Risco médio", risco.MEDIO || 0, "medio"),
      card("Sem apontamento", risco.BAIXO || 0, "baixo"),
      card("Pendentes", status.PENDENTE || 0, ""),
      card("Revisão humana", dados.revisao_humana, "destaque"),
    ].join("");

    const badge = document.getElementById("badge-monitoramento");
    if (badge) badge.textContent = dados.revisao_humana || 0;
  }

  function card(rotulo, valor, classe) {
    return `<div class="card ${classe}"><b>${Number(valor).toLocaleString("pt-BR")}</b><span>${e(rotulo)}</span></div>`;
  }

  async function carregarTabela() {
    corpo.innerHTML = '<tr><td colspan="7" class="carregando">Carregando…</td></tr>';
    ultimaLista = await API.monitoramento(filtros());

    vazio.hidden = ultimaLista.length > 0;
    corpo.innerHTML = ultimaLista.map((linha, indice) => {
      const classe = Formato.classeRisco(linha.classificacao_risco);
      const alerta = linha.divergencia_regex
        ? '<span class="aviso-divergencia">⚠ Diverge da leitura automática</span>'
        : (linha.celula_invalida ? '<span class="aviso-divergencia">⚠ Fora da matriz</span>' : "");

      return `
        <tr>
          <td class="col-nome">
            <strong>${e(Formato.encurtar(linha.nome || "(fora do cadastro)", 46))}</strong>
            <span>${e(Formato.cnpj(linha.fundo_cnpj))}</span>${alerta}
          </td>
          <td class="num">${e(linha.ano_referencia)}</td>
          <td>${e(Formato.manifestacao(linha.manifestacao))}</td>
          <td><span class="pilula ${classe}">${e(Formato.risco(linha.classificacao_risco))}</span></td>
          <td class="col-just">${e(Formato.encurtar(linha.justificativa, 130))}</td>
          <td>
            <select data-id="${linha.id}" class="seletor-status">
              ${STATUS.map((s) => `<option value="${s}"${s === linha.status_analista ? " selected" : ""}>${s[0]}${s.slice(1).toLowerCase()}</option>`).join("")}
            </select>
          </td>
          <td><button class="botao-link" data-indice="${indice}">Ver análise</button></td>
        </tr>`;
    }).join("");

    ligarEventos();
  }

  function ligarEventos() {
    corpo.querySelectorAll(".seletor-status").forEach((seletor) => {
      seletor.addEventListener("change", async (ev) => {
        const anterior = ultimaLista.find((l) => String(l.id) === ev.target.dataset.id);
        try {
          await API.mudarStatus(ev.target.dataset.id, ev.target.value);
          if (anterior) anterior.status_analista = ev.target.value;
          carregarIndicadores();
        } catch (_) {
          // Reverte o select para o valor real: nao deixar a tela mentir que salvou.
          if (anterior) ev.target.value = anterior.status_analista;
          alert("Não foi possível salvar o status.");
        }
      });
    });

    corpo.querySelectorAll(".botao-link").forEach((botao) => {
      botao.addEventListener("click", () => aoAbrirAnalise(ultimaLista[Number(botao.dataset.indice)]));
    });
  }

  function ligarFiltros() {
    const recarregar = () => carregarTabela();
    ["f-risco", "f-status"].forEach((id) =>
      document.getElementById(id).addEventListener("change", recarregar));
    document.getElementById("f-revisao").addEventListener("change", recarregar);
    document.getElementById("f-administrador").addEventListener("input", () => {
      clearTimeout(temporizador);
      temporizador = setTimeout(recarregar, 320);
    });
  }

  async function carregarListaNegativa() {
    const linhas = await API.listaNegativa();
    const corpoLista = document.querySelector("#tabela-lista tbody");
    document.getElementById("lista-vazia").hidden = linhas.length > 0;
    corpoLista.innerHTML = linhas.map((l) => `
      <tr>
        <td><strong>${e(l.nome || "(fora do cadastro)")}</strong></td>
        <td><span style="font-family:var(--mono);font-size:11px">${e(Formato.cnpj(l.fundo_cnpj))}</span></td>
        <td>${e(l.administrador_nome || "—")}</td>
        <td class="col-just">${e(l.motivo)}</td>
        <td class="num">${e(Formato.data(l.incluido_em))}</td>
      </tr>`).join("");

    const badge = document.getElementById("badge-lista");
    if (badge) badge.textContent = linhas.length;
  }

  return {
    iniciar() { ligarFiltros(); },
    carregar() { return Promise.all([carregarIndicadores(), carregarTabela()]); },
    carregarListaNegativa,
    carregarIndicadores,
    aoAbrirAnalise(callback) { aoAbrirAnalise = callback; },
  };
})();
