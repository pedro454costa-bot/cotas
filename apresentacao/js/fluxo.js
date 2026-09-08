/* Fluxo da infraestrutura: ligacoes e particulas entre os cartoes.

   Abordagem hibrida de proposito. Os NOS sao HTML - texto nitido em qualquer
   zoom, estilo em CSS, responsivo de graca. As LIGACOES sao canvas, porque
   particula viajando por curva e coisa que DOM nao faz bem.

   O canvas le a posicao real dos cartoes com getBoundingClientRect e desenha
   por cima. Assim o layout continua sendo responsabilidade do CSS: se o grid
   quebrar em telas menores, as linhas acompanham sem nenhum ajuste manual.
*/

(() => {
  const canvas = document.getElementById("fluxo-linhas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const mapa = canvas.parentElement;

  const REDUZIR = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const AZUL    = [110, 155, 255];
  const VIOLETA = [164, 123, 255];
  const CIANO   = [ 79, 227, 208];
  const CINZA   = [ 96, 106, 126];

  /* [origem, destino, cor, ehCaminhoDeIA] */
  const LIGACOES = [
    ["cvm", "df",  CINZA, false],
    ["cvm", "fr",  CINZA, false],
    ["cvm", "cda", CINZA, false],

    ["df",  "ia-df",  VIOLETA, true],
    ["fr",  "ia-fr",  VIOLETA, true],
    ["cda", "cadeia", AZUL,    false],

    ["ia-df",  "risco", VIOLETA, true],
    ["ia-fr",  "risco", VIOLETA, true],
    ["cadeia", "risco", AZUL,    false],
  ];

  let caixas = new Map();
  let particulas = [];
  let l = 0, a = 0, dpr = 1;
  let rodando = false, quadro = null, tempo = 0;

  /* --------------------------------------------------------- geometria -- */

  function medir() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const r = mapa.getBoundingClientRect();
    l = r.width; a = r.height;
    canvas.width = l * dpr;
    canvas.height = a * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    caixas = new Map();
    mapa.querySelectorAll("[data-no]").forEach((el) => {
      const c = el.getBoundingClientRect();
      caixas.set(el.dataset.no, {
        // Coordenadas relativas ao mapa, nao a janela.
        esq:   c.left - r.left,
        dir:   c.right - r.left,
        meioY: c.top - r.top + c.height / 2,
      });
    });
  }

  /* Saida pela direita do cartao de origem, entrada pela esquerda do destino:
     a leitura do fluxo fica sempre da esquerda para a direita. */
  function extremos(de, para) {
    const A = caixas.get(de), B = caixas.get(para);
    if (!A || !B) return null;
    return { x1: A.dir + 3, y1: A.meioY, x2: B.esq - 3, y2: B.meioY };
  }

  /* Bezier com controles horizontais: a curva sai e entra na horizontal,
     independentemente da diferenca de altura. E o que da o aspecto de
     diagrama de fluxo em vez de linha torta. */
  function ponto(e, t) {
    const dx = Math.max((e.x2 - e.x1) * 0.5, 26);
    const c1x = e.x1 + dx, c2x = e.x2 - dx;
    const u = 1 - t;
    return {
      x: u*u*u*e.x1 + 3*u*u*t*c1x + 3*u*t*t*c2x + t*t*t*e.x2,
      y: u*u*u*e.y1 + 3*u*u*t*e.y1 + 3*u*t*t*e.y2 + t*t*t*e.y2,
    };
  }

  function traçar(e) {
    const dx = Math.max((e.x2 - e.x1) * 0.5, 26);
    ctx.beginPath();
    ctx.moveTo(e.x1, e.y1);
    ctx.bezierCurveTo(e.x1 + dx, e.y1, e.x2 - dx, e.y2, e.x2, e.y2);
  }

  /* --------------------------------------------------------- desenho --- */

  function nascerParticula() {
    if (REDUZIR || particulas.length > 26) return;
    const i = (Math.random() * LIGACOES.length) | 0;
    const [de, para, cor, ehIA] = LIGACOES[i];
    if (!caixas.has(de) || !caixas.has(para)) return;
    particulas.push({
      de, para, cor, ehIA,
      t: 0,
      // Trecho de IA anda mais devagar: sugere processamento, nao transporte.
      velocidade: (ehIA ? 0.0038 : 0.0062) + Math.random() * 0.0022,
    });
  }

  function desenhar(agora) {
    ctx.clearRect(0, 0, l, a);

    for (const [de, para, cor, ehIA] of LIGACOES) {
      const e = extremos(de, para);
      if (!e) continue;

      traçar(e);
      ctx.strokeStyle = `rgba(${cor[0]},${cor[1]},${cor[2]},${ehIA ? .34 : .18})`;
      ctx.lineWidth = ehIA ? 1.5 : 1;
      // Tracejado em marcha nos trechos de IA: mesmo sem particula passando,
      // fica visivel que aquele caminho e o "vivo" do diagrama.
      if (ehIA && !REDUZIR) {
        ctx.setLineDash([5, 7]);
        ctx.lineDashOffset = -agora * 0.022;
      } else {
        ctx.setLineDash([]);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }

    for (let i = particulas.length - 1; i >= 0; i--) {
      const p = particulas[i];
      p.t += p.velocidade;
      if (p.t >= 1) { particulas.splice(i, 1); continue; }

      const e = extremos(p.de, p.para);
      if (!e) { particulas.splice(i, 1); continue; }

      const { x, y } = ponto(e, p.t);
      const forca = Math.sin(p.t * Math.PI);   // nasce e morre nas pontas
      const [r, g, b] = p.cor;

      const halo = ctx.createRadialGradient(x, y, 0, x, y, 11);
      halo.addColorStop(0, `rgba(${r},${g},${b},${.62 * forca})`);
      halo.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(x, y, 11, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = `rgba(255,255,255,${.92 * forca})`;
      ctx.beginPath();
      ctx.arc(x, y, p.ehIA ? 2.4 : 1.8, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function laco(agora) {
    if (!rodando) return;
    tempo = agora;
    if (Math.random() < 0.07) nascerParticula();
    desenhar(agora);
    quadro = requestAnimationFrame(laco);
  }

  function iniciar() {
    if (rodando) return;
    rodando = true;
    // Um quadro de atraso: o CSS precisa aplicar a entrada dos cartoes antes
    // de medirmos, senao as linhas nascem nas posicoes erradas.
    requestAnimationFrame(() => {
      medir();
      quadro = requestAnimationFrame(laco);
    });
  }

  function parar() {
    rodando = false;
    if (quadro) cancelAnimationFrame(quadro);
    quadro = null;
    particulas = [];
    ctx.clearRect(0, 0, l, a);
  }

  const observador = new IntersectionObserver((entradas) => {
    for (const e of entradas) e.isIntersecting ? iniciar() : parar();
  }, { threshold: 0.3 });

  const slide = canvas.closest(".slide");
  if (slide) observador.observe(slide);

  window.addEventListener("resize", () => { if (rodando) medir(); });
})();
