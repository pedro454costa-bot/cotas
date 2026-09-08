/* Asteroide atravessando o slide da interface.

   Desenhado em canvas, nao e imagem: a silhueta e um poligono irregular
   gerado uma unica vez, e o que da a leitura de "rocha" sao tres camadas -
   sombreamento direcional, crateras e borda iluminada.

   A travessia acontece a cada ~14 segundos e leva ~11. Espacamento longo de
   proposito: o asteroide e um acento, nao um elemento de cena. Se cruzasse a
   toda hora viraria distracao em cima do texto.

   So anima enquanto o slide esta visivel - fora dele o laco para.
*/

(() => {
  const canvas = document.getElementById("asteroide");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const REDUZIR = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const INTERVALO_MIN = 9000;
  const INTERVALO_MAX = 17000;
  const DURACAO = 11000;

  let l = 0, a = 0, dpr = 1;
  let rodando = false;
  let quadro = null;

  let silhueta = [];
  let crateras = [];
  let travessia = null;
  let proxima = 0;

  /* ------------------------------------------------------------ forma -- */

  /* Poligono irregular: raio sorteado por vertice, com variacao suficiente
     para nao parecer circulo nem estrela. */
  function gerarSilhueta() {
    const lados = 11;
    silhueta = [];
    for (let i = 0; i < lados; i++) {
      const angulo = (i / lados) * Math.PI * 2;
      silhueta.push({ angulo, raio: 0.72 + Math.random() * 0.38 });
    }

    crateras = [];
    for (let i = 0; i < 6; i++) {
      const angulo = Math.random() * Math.PI * 2;
      const d = Math.random() * 0.55;
      crateras.push({
        x: Math.cos(angulo) * d,
        y: Math.sin(angulo) * d,
        raio: 0.07 + Math.random() * 0.15,
      });
    }
  }

  function dimensionar() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const caixa = canvas.getBoundingClientRect();
    l = caixa.width; a = caixa.height;
    canvas.width = l * dpr;
    canvas.height = a * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function agendar(agora) {
    proxima = agora + INTERVALO_MIN + Math.random() * (INTERVALO_MAX - INTERVALO_MIN);
  }

  function lancar() {
    const daEsquerda = Math.random() > 0.35;
    const tamanho = 16 + Math.random() * 22;
    travessia = {
      inicio: performance.now(),
      daEsquerda,
      // Entra e sai bem fora da tela: nunca se ve o asteroide "aparecer".
      x0: daEsquerda ? -120 : l + 120,
      x1: daEsquerda ? l + 120 : -120,
      y0: a * (0.12 + Math.random() * 0.30),
      y1: a * (0.55 + Math.random() * 0.35),
      tamanho,
      giro: (Math.random() - 0.5) * 0.9,
      rastro: [],
    };
  }

  /* ---------------------------------------------------------- desenho -- */

  function desenharRocha(x, y, r, rotacao) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(rotacao);

    ctx.beginPath();
    silhueta.forEach((v, i) => {
      const px = Math.cos(v.angulo) * v.raio * r;
      const py = Math.sin(v.angulo) * v.raio * r;
      i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    });
    ctx.closePath();

    // Luz vindo de cima-esquerda: o gradiente e o que transforma o poligono
    // chapado em volume.
    const luz = ctx.createLinearGradient(-r, -r, r, r);
    luz.addColorStop(0, "#8A8477");
    luz.addColorStop(0.42, "#4E4A44");
    luz.addColorStop(1, "#22201E");
    ctx.fillStyle = luz;
    ctx.fill();

    // Crateras: circulos mais escuros com meia-lua clara na borda oposta.
    ctx.clip();
    for (const c of crateras) {
      const cx = c.x * r, cy = c.y * r, cr = c.raio * r;
      ctx.fillStyle = "rgba(20,19,18,.55)";
      ctx.beginPath();
      ctx.arc(cx, cy, cr, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(180,172,158,.22)";
      ctx.lineWidth = Math.max(cr * .22, .5);
      ctx.beginPath();
      ctx.arc(cx + cr * .12, cy + cr * .12, cr * .86, Math.PI * .8, Math.PI * 1.9);
      ctx.stroke();
    }
    ctx.restore();

    // Borda iluminada por cima do recorte, so no lado da luz.
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(rotacao);
    ctx.beginPath();
    silhueta.forEach((v, i) => {
      const px = Math.cos(v.angulo) * v.raio * r;
      const py = Math.sin(v.angulo) * v.raio * r;
      i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    });
    ctx.closePath();
    const borda = ctx.createLinearGradient(-r, -r, r * .4, r * .4);
    borda.addColorStop(0, "rgba(226,218,200,.55)");
    borda.addColorStop(.55, "rgba(226,218,200,0)");
    ctx.strokeStyle = borda;
    ctx.lineWidth = 1.1;
    ctx.stroke();
    ctx.restore();
  }

  function desenhar(agora) {
    ctx.clearRect(0, 0, l, a);
    if (!travessia) return;

    const t = (agora - travessia.inicio) / DURACAO;
    if (t >= 1) { travessia = null; agendar(agora); return; }

    const x = travessia.x0 + (travessia.x1 - travessia.x0) * t;
    // Trajetoria levemente curva: linha reta perfeita denuncia a animacao.
    const y = travessia.y0 + (travessia.y1 - travessia.y0) * t
            + Math.sin(t * Math.PI) * 28;
    // Entra e sai em fade, para nao surgir do nada nas bordas do canvas.
    const opacidade = Math.min(t / .12, 1) * Math.min((1 - t) / .12, 1);

    travessia.rastro.push({ x, y, vida: 1 });
    if (travessia.rastro.length > 34) travessia.rastro.shift();

    // Poeira: pontos que ficam para tras e se apagam.
    for (let i = 0; i < travessia.rastro.length; i++) {
      const p = travessia.rastro[i];
      p.vida -= .028;
      if (p.vida <= 0) continue;
      const forca = p.vida * (i / travessia.rastro.length) * opacidade;
      ctx.fillStyle = `rgba(198,188,170,${forca * .30})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, travessia.tamanho * .16 * p.vida, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalAlpha = opacidade;
    desenharRocha(x, y, travessia.tamanho, agora * .0004 * travessia.giro);
    ctx.globalAlpha = 1;
  }

  function laco(agora) {
    if (!rodando) return;
    if (!travessia && agora >= proxima) lancar();
    desenhar(agora);
    quadro = requestAnimationFrame(laco);
  }

  function iniciar() {
    if (rodando || REDUZIR) return;
    rodando = true;
    dimensionar();
    // Primeira travessia logo apos a entrada do slide, sem esperar o intervalo
    // cheio - senao a pessoa passa pelo slide e nunca ve o asteroide.
    proxima = performance.now() + 1400;
    quadro = requestAnimationFrame(laco);
  }

  function parar() {
    rodando = false;
    if (quadro) cancelAnimationFrame(quadro);
    quadro = null;
    travessia = null;
    ctx.clearRect(0, 0, l, a);
  }

  /* Liga e desliga conforme o slide entra e sai da tela. */
  const observador = new IntersectionObserver((entradas) => {
    for (const entrada of entradas) {
      entrada.isIntersecting ? iniciar() : parar();
    }
  }, { threshold: 0.35 });

  const slide = canvas.closest(".slide");
  if (slide) observador.observe(slide);

  gerarSilhueta();
  window.addEventListener("resize", () => { if (rodando) dimensionar(); });
})();
