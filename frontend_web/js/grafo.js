/* Grafo da cadeia de investimentos - canvas escuro, nos com brilho.

   O desenho de cada no e feito a mao no canvas (shape "custom") em vez de usar
   os shapes prontos do vis-network. E o unico jeito de ter halo real: um
   gradiente radial que vaza para fora do circulo, como no Obsidian. Shape
   pronto so aceita sombra dura, que num fundo escuro fica suja.

   Tres decisoes de legibilidade:

   - TAMANHO = exposicao do fundo raiz. Numa cadeia master/feeder o que importa
     nao e o patrimonio do investido, e quanto do fundo analisado chega ali.
   - ARESTA nao tem rotulo. Percentual e valor em cada linha e o que deixava o
     grafo ilegivel; agora vao no hover.
   - ROTULO so aparece em no relevante ou sob o cursor. Vinte nomes sobrepostos
     nao informam nada.
*/

const Grafo = (() => {
  /* Cores vivas, calibradas para fundo escuro. */
  const PALETA = {
    ALTO:  { nucleo: "#FF4D5E", halo: "#FF4D5E", texto: "#FFB3BA" },
    MEDIO: { nucleo: "#FFB020", halo: "#FFB020", texto: "#FFD98F" },
    BAIXO: { nucleo: "#31D0AA", halo: "#31D0AA", texto: "#9BEBD7" },
    NULO:  { nucleo: "#6E7A8A", halo: "#6E7A8A", texto: "#A8B2BF" },
    RAIZ:  { nucleo: "#FFFFFF", halo: "#8AB4FF", texto: "#FFFFFF" },
    LISTA: { nucleo: "#FF2D55", halo: "#FF2D55", texto: "#FF99AB" },
  };

  const FUNDO = "#12141A";

  /* Pulso de alerta nos nos criticos. Duracao longa de proposito: onda rapida
     vira ruido nervoso; a 2,4s a leitura e de radar, nao de piscar. */
  const PULSO_MS = 2400;
  const PULSO_ONDAS = 3;
  const FPS_PULSO = 30;

  // Quem pediu para reduzir animacao no sistema nao recebe pulso nenhum.
  const REDUZIR_MOVIMENTO =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const RAIO_MIN = 5;
  const RAIO_MAX = 26;
  const LIMITE_ROTULO = 11;   // abaixo deste raio o nome so aparece no hover

  let rede = null;
  let aoClicarNo = () => {};
  let aoDuploClicarNo = () => {};
  let animacao = null;
  // Lido por referencia dentro dos ctxRenderer, que sao criados uma unica vez.
  const relogio = { agora: 0 };

  function paleta(no, naLista) {
    if (naLista) return PALETA.LISTA;
    if (no.eh_raiz) return PALETA.RAIZ;
    return PALETA[no.classificacao_risco] || PALETA.NULO;
  }

  function raio(no) {
    if (no.eh_raiz) return 22;
    const pct = Math.max(no.percentual_do_raiz || 0, 0);
    // Raiz quadrada comprime a escala: sem isso uma posicao de 88% esmaga
    // visualmente todas as de 1-5%, que sao a maioria.
    return Math.min(RAIO_MIN + Math.sqrt(pct) * 2.6, RAIO_MAX);
  }

  function hexParaRgba(hex, alfa) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alfa})`;
  }

  /* ------------------------------------------------------- desenho do no -- */

  /* Ondas concentricas expandindo a partir do no, como um radar.

     As ondas sao defasadas entre si (k / PULSO_ONDAS) para haver sempre uma
     nascendo enquanto outra se dissipa - com uma onda so o efeito fica
     intermitente. O alfa cai com o cubo do avanco: a onda some bem antes da
     borda, evitando anel duro no fim do ciclo. */
  function desenharPulso(ctx, x, y, r, cor, tempo, alfa) {
    for (let k = 0; k < PULSO_ONDAS; k++) {
      const avanco = ((tempo / PULSO_MS) + k / PULSO_ONDAS) % 1;
      const raioOnda = r * (1 + avanco * 2.6);
      const opacidade = Math.pow(1 - avanco, 3) * 0.55 * alfa;
      if (opacidade < 0.01) continue;

      ctx.strokeStyle = hexParaRgba(cor, opacidade);
      ctx.lineWidth = Math.max(2.2 * (1 - avanco), 0.5);
      ctx.beginPath();
      ctx.arc(x, y, raioOnda, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  function desenharNo(ctx, x, y, r, cores, destacado, atenuado, pulsa, tempo) {
    const alfa = atenuado ? 0.18 : 1;

    // Antes do halo: as ondas ficam por baixo do no, nunca por cima do rotulo.
    if (pulsa && !REDUZIR_MOVIMENTO) desenharPulso(ctx, x, y, r, cores.halo, tempo, alfa);

    // 1. Halo: gradiente radial que vaza bem alem do circulo.
    const forcaHalo = destacado ? 4.2 : 3.0;
    const halo = ctx.createRadialGradient(x, y, r * 0.5, x, y, r * forcaHalo);
    halo.addColorStop(0, hexParaRgba(cores.halo, 0.55 * alfa));
    halo.addColorStop(0.45, hexParaRgba(cores.halo, 0.16 * alfa));
    halo.addColorStop(1, hexParaRgba(cores.halo, 0));
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(x, y, r * forcaHalo, 0, Math.PI * 2);
    ctx.fill();

    // 2. Nucleo com leve degrade, para o no nao parecer um adesivo chapado.
    const nucleo = ctx.createRadialGradient(x - r * 0.3, y - r * 0.35, r * 0.1, x, y, r);
    nucleo.addColorStop(0, hexParaRgba(cores.nucleo, 1 * alfa));
    nucleo.addColorStop(1, hexParaRgba(cores.nucleo, 0.72 * alfa));
    ctx.fillStyle = nucleo;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();

    // 3. Anel externo: separa o no do halo e marca a selecao.
    ctx.strokeStyle = hexParaRgba("#FFFFFF", (destacado ? 0.75 : 0.22) * alfa);
    ctx.lineWidth = destacado ? 2 : 1;
    ctx.beginPath();
    ctx.arc(x, y, r + 1.5, 0, Math.PI * 2);
    ctx.stroke();
  }

  function desenharRotulo(ctx, x, y, r, texto, cores, forte, atenuado) {
    if (!texto) return;
    const alfa = atenuado ? 0.15 : 1;
    ctx.font = `${forte ? 600 : 400} ${forte ? 12 : 11}px "Segoe UI", sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";

    // Contorno escuro atras do texto: sobre aresta ou halo, texto puro some.
    ctx.lineWidth = 3;
    ctx.strokeStyle = hexParaRgba(FUNDO, 0.85 * alfa);
    ctx.strokeText(texto, x, y + r + 7);
    ctx.fillStyle = hexParaRgba(forte ? "#FFFFFF" : cores.texto, (forte ? 0.95 : 0.8) * alfa);
    ctx.fillText(texto, x, y + r + 7);
  }

  /* ------------------------------------------------------------- montagem -- */

  function montarNos(dados, bloqueados, foco) {
    return dados.nos.map((no) => {
      const naLista = bloqueados.has(no.cnpj);
      const cores = paleta(no, naLista);
      const r = raio(no);
      const nome = Formato.encurtar(no.nome || no.cnpj, 30);
      // So o que exige acao do analista pulsa. Se tudo pulsasse, nada chamaria.
      const pulsa = naLista || no.classificacao_risco === "ALTO";

      return {
        id: no.cnpj,
        label: nome,
        shape: "custom",
        dadosFundo: no,
        title: dica(no, bloqueados.has(no.cnpj)),
        ctxRenderer({ ctx, x, y, state: { selected, hover } }) {
          const destacado = selected || hover;
          // Quando ha um no em foco, o resto do grafo recua em vez de sumir:
          // o contexto continua visivel, sem competir pela atencao.
          const atenuado = foco.valor !== null && foco.valor !== no.cnpj && !destacado;
          return {
            drawNode: () => desenharNo(ctx, x, y, r, cores, destacado, atenuado,
                                       pulsa, relogio.agora),
            drawExternalLabel: () => {
              const mostrar = no.eh_raiz || r >= LIMITE_ROTULO || destacado;
              if (mostrar) desenharRotulo(ctx, x, y, r, nome, cores, no.eh_raiz || destacado, atenuado);
            },
            nodeDimensions: { width: r * 2, height: r * 2 },
          };
        },
      };
    });
  }

  function dica(no, naLista) {
    return [
      no.nome || no.cnpj,
      Formato.cnpj(no.cnpj),
      no.classe ? `Classe: ${no.classe}` : null,
      no.eh_raiz ? null : `Exposição: ${Formato.percentual(no.percentual_do_raiz)} do fundo raiz`,
      `Risco: ${Formato.risco(no.classificacao_risco)}`,
      naLista ? "⛔ Lista negativa" : null,
      no.motivo_risco ? `\n${Formato.encurtar(no.motivo_risco, 140)}` : null,
    ].filter(Boolean).join("\n");
  }

  function montarArestas(dados, riscoPorCnpj, bloqueados) {
    const maximo = Math.max(...dados.arestas.map((a) => a.valor || 0), 1);

    return dados.arestas.map((aresta) => {
      const risco = riscoPorCnpj.get(aresta.destino);
      const critico = risco === "ALTO" || bloqueados.has(aresta.destino);
      const cor = critico ? PALETA.ALTO.nucleo : (risco === "MEDIO" ? PALETA.MEDIO.nucleo : "#3A4351");

      return {
        from: aresta.origem,
        to: aresta.destino,
        width: 0.6 + (aresta.valor || 0) / maximo * 2.4,
        color: {
          color: hexParaRgba(cor, critico ? 0.55 : 0.32),
          highlight: hexParaRgba(cor, 0.95),
          hover: hexParaRgba(cor, 0.9),
        },
        smooth: { type: "curvedCW", roundness: 0.14 },
        arrows: { to: { enabled: false } },
        // Sem rotulo fixo: percentual e valor em toda linha era o que tornava o
        // grafo ilegivel. A informacao continua acessivel no hover.
        title: `${Formato.percentual(aresta.percentual_pl)} do PL · ${Formato.dinheiro(aresta.valor)} · ${aresta.competencia}`,
      };
    });
  }

  const OPCOES = {
    physics: {
      solver: "forceAtlas2Based",
      forceAtlas2Based: {
        gravitationalConstant: -95,
        centralGravity: 0.006,
        springLength: 190,
        springConstant: 0.055,
        avoidOverlap: 0.7,
        damping: 0.55,
      },
      stabilization: { iterations: 320, updateInterval: 30 },
      timestep: 0.4,
    },
    interaction: {
      hover: true,
      tooltipDelay: 120,
      hideEdgesOnDrag: true,
      zoomView: true,
      dragView: true,
      navigationButtons: false,
    },
    edges: { selectionWidth: 0 },
    nodes: { borderWidth: 0 },
    layout: { improvedLayout: true },
  };

  function desenhar(container, dados, bloqueados = new Set()) {
    if (typeof vis === "undefined" || !vis.DataSet || !vis.Network) {
      throw new Error(
        "vis-network não carregou. Confira vendor/vis-network.min.js "
        + "(precisa ser o build standalone/umd, que define o global vis)."
      );
    }

    const riscoPorCnpj = new Map(dados.nos.map((n) => [n.cnpj, n.classificacao_risco]));
    // Objeto e nao valor solto: os ctxRenderer leem por referencia, entao mudar
    // foco.valor repinta sem precisar remontar o DataSet inteiro.
    const foco = { valor: null };

    const nos = new vis.DataSet(montarNos(dados, bloqueados, foco));
    const arestas = new vis.DataSet(montarArestas(dados, riscoPorCnpj, bloqueados));

    destruir();
    rede = new vis.Network(container, { nodes: nos, edges: arestas }, OPCOES);

    const temCritico = dados.nos.some(
      (n) => n.classificacao_risco === "ALTO" || bloqueados.has(n.cnpj)
    );

    rede.once("stabilizationIterationsDone", () => {
      rede.setOptions({ physics: false });
      rede.fit({ animation: { duration: 420, easingFunction: "easeInOutQuad" } });
      iniciarPulso(temCritico);
    });

    /* Clique simples abre o fundo no painel; duplo clique o promove a raiz do
       grafo. O vis-network dispara "click" duas vezes antes do "doubleClick",
       entao o painel pisca no fundo certo antes de a analise completa entrar -
       o que e coerente, e nao atrapalha. */
    rede.on("click", (evento) => {
      if (!evento.nodes.length) {
        foco.valor = null;
        rede.redraw();
        return;
      }
      const no = nos.get(evento.nodes[0]);
      foco.valor = no.id;
      rede.redraw();
      if (no.dadosFundo) aoClicarNo(no.dadosFundo);
    });

    rede.on("doubleClick", (evento) => {
      if (!evento.nodes.length) return;
      const no = nos.get(evento.nodes[0]);
      // Reanalisar a propria raiz so recarregaria a mesma tela.
      if (no && no.dadosFundo && !no.dadosFundo.eh_raiz) aoDuploClicarNo(no.dadosFundo);
    });

    rede.on("hoverNode", () => { container.style.cursor = "pointer"; });
    rede.on("blurNode", () => { container.style.cursor = "default"; });

    return rede;
  }

  /* Com a fisica desligada o vis-network so repinta sob interacao, entao o
     pulso precisa de um loop proprio. Ele so roda se existir no critico - num
     grafo todo verde nao ha animacao consumindo CPU a toa. */
  function iniciarPulso(temCritico) {
    pararPulso();
    if (!temCritico || REDUZIR_MOVIMENTO) return;

    const intervalo = 1000 / FPS_PULSO;
    let ultimo = 0;
    const passo = (agora) => {
      if (!rede) return;
      if (agora - ultimo >= intervalo) {
        relogio.agora = agora;
        rede.redraw();
        ultimo = agora;
      }
      animacao = requestAnimationFrame(passo);
    };
    animacao = requestAnimationFrame(passo);
  }

  function pararPulso() {
    if (animacao !== null) { cancelAnimationFrame(animacao); animacao = null; }
  }

  function aoSelecionar(callback) { aoClicarNo = callback; }
  function aoDuploClicar(callback) { aoDuploClicarNo = callback; }

  function destruir() {
    pararPulso();
    if (rede) { rede.destroy(); rede = null; }
  }

  return { desenhar, aoSelecionar, aoDuploClicar, destruir };
})();
