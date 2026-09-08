/* Campo estelar com parallax. Canvas puro, sem biblioteca.

   Tres camadas com velocidades diferentes: as estrelas de tras quase nao se
   movem, as da frente acompanham a rolagem. E o que cria sensacao de
   profundidade sem nenhum efeito 3D de verdade.
*/

(() => {
  const canvas = document.getElementById("ceu");
  const ctx = canvas.getContext("2d");

  const REDUZIR = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const CAMADAS = [
    { quantidade: 260, raio: [0.4, 0.9], parallax: 0.06, alfa: [0.18, 0.42] },
    { quantidade: 130, raio: [0.7, 1.5], parallax: 0.16, alfa: [0.34, 0.68] },
    { quantidade: 55,  raio: [1.2, 2.3], parallax: 0.32, alfa: [0.55, 0.95] },
  ];

  const MATIZES = ["#FFFFFF", "#CFE0FF", "#E8DCFF", "#C9F5EE"];

  let estrelas = [];
  let cometas = [];
  let largura = 0, altura = 0, dpr = 1;
  let deslocamento = 0;
  let tempo = 0;

  function aleatorio(min, max) { return min + Math.random() * (max - min); }

  function dimensionar() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    largura = window.innerWidth;
    altura = window.innerHeight;
    canvas.width = largura * dpr;
    canvas.height = altura * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    gerar();
  }

  function gerar() {
    estrelas = [];
    for (const camada of CAMADAS) {
      for (let i = 0; i < camada.quantidade; i++) {
        estrelas.push({
          x: Math.random() * largura,
          // Distribui em 3 alturas de tela: ao rolar, sempre ha estrela nova.
          y: Math.random() * altura * 3,
          raio: aleatorio(camada.raio[0], camada.raio[1]),
          alfa: aleatorio(camada.alfa[0], camada.alfa[1]),
          parallax: camada.parallax,
          cor: MATIZES[(Math.random() * MATIZES.length) | 0],
          fase: Math.random() * Math.PI * 2,
          brilho: Math.random() < 0.22,     // so algumas cintilam
        });
      }
    }
  }

  /* Cometa ocasional: evento raro de proposito. Se fosse frequente viraria
     ruido; a cada ~9 segundos ele surpreende sem cansar. */
  function talvezCometa() {
    if (REDUZIR || Math.random() > 0.004 || cometas.length > 1) return;
    const doTopo = Math.random() > 0.5;
    cometas.push({
      x: aleatorio(largura * 0.1, largura * 0.9),
      y: doTopo ? -40 : aleatorio(0, altura * 0.4),
      vx: aleatorio(2.4, 4.2) * (Math.random() > 0.5 ? 1 : -1),
      vy: aleatorio(1.8, 3.4),
      vida: 1,
      comprimento: aleatorio(70, 150),
    });
  }

  function desenharCometas() {
    for (let i = cometas.length - 1; i >= 0; i--) {
      const c = cometas[i];
      c.x += c.vx; c.y += c.vy; c.vida -= 0.007;
      if (c.vida <= 0 || c.y > altura + 80) { cometas.splice(i, 1); continue; }

      const norma = Math.hypot(c.vx, c.vy);
      const tx = c.x - (c.vx / norma) * c.comprimento;
      const ty = c.y - (c.vy / norma) * c.comprimento;

      const rastro = ctx.createLinearGradient(c.x, c.y, tx, ty);
      rastro.addColorStop(0, `rgba(220,235,255,${0.85 * c.vida})`);
      rastro.addColorStop(1, "rgba(220,235,255,0)");
      ctx.strokeStyle = rastro;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(c.x, c.y);
      ctx.lineTo(tx, ty);
      ctx.stroke();
    }
  }

  function desenhar() {
    ctx.clearRect(0, 0, largura, altura);

    for (const e of estrelas) {
      // O modulo faz a estrela reaparecer do outro lado - ceu infinito.
      const y = ((e.y - deslocamento * e.parallax) % (altura * 3) + altura * 3) % (altura * 3);
      if (y < -10 || y > altura + 10) continue;

      const cintila = e.brilho && !REDUZIR
        ? 0.55 + Math.sin(tempo * 0.0018 + e.fase) * 0.45
        : 1;
      const alfa = e.alfa * cintila;

      if (e.raio > 1.1) {
        const halo = ctx.createRadialGradient(e.x, y, 0, e.x, y, e.raio * 4.5);
        halo.addColorStop(0, corAlfa(e.cor, alfa * 0.4));
        halo.addColorStop(1, corAlfa(e.cor, 0));
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(e.x, y, e.raio * 4.5, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.fillStyle = corAlfa(e.cor, alfa);
      ctx.beginPath();
      ctx.arc(e.x, y, e.raio, 0, Math.PI * 2);
      ctx.fill();
    }

    talvezCometa();
    desenharCometas();
  }

  function corAlfa(hex, alfa) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alfa})`;
  }

  function laco(agora) {
    tempo = agora;
    deslocamento = window.scrollY;
    desenhar();
    requestAnimationFrame(laco);
  }

  window.addEventListener("resize", dimensionar);
  dimensionar();
  requestAnimationFrame(laco);
})();
