/* Constelacao viva da capa: rede que se forma, respira e transporta dados.

   Tres camadas de comportamento, sobrepostas:

   1. NOS derivam devagar num campo de ruido suave. Sem destino, sem colisao -
      o movimento precisa parecer respiracao, nao trafego.
   2. LIGACOES nascem por PROXIMIDADE, nao por lista fixa. A rede se reorganiza
      sozinha o tempo todo: e o que faz parecer viva em vez de animada.
   3. PULSOS viajam pelas ligacoes, sempre da esquerda para a direita. Sao o
      "ponta a ponta" do titulo: dado bruto entrando de um lado, risco
      calculado saindo do outro.

   O cursor abre espaco ao redor - repulsao suave que volta sozinha.
*/

(() => {
  const canvas = document.getElementById("capa-rede");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const REDUZIR = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const CORES = ["#6E9BFF", "#A47BFF", "#4FE3D0", "#FFFFFF"];
  const PESOS = [0.42, 0.26, 0.22, 0.10];   // frequencia de cada cor

  const DISTANCIA_LIGACAO = 132;
  const RAIO_CURSOR = 150;

  let nos = [];
  let pulsos = [];
  let l = 0, a = 0, dpr = 1;
  let tempo = 0;
  let cursor = { x: -9999, y: -9999 };

  function sortearCor() {
    let r = Math.random();
    for (let i = 0; i < PESOS.length; i++) {
      r -= PESOS[i];
      if (r <= 0) return CORES[i];
    }
    return CORES[0];
  }

  function quantidade() {
    // Densidade constante por area: em tela larga a rede nao fica rala.
    return Math.round(Math.min(Math.max((l * a) / 13000, 60), 150));
  }

  function dimensionar() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const caixa = canvas.getBoundingClientRect();
    l = caixa.width; a = caixa.height;
    canvas.width = l * dpr;
    canvas.height = a * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    gerar();
  }

  function gerar() {
    nos = [];
    const total = quantidade();
    for (let i = 0; i < total; i++) {
      const raio = 1.1 + Math.random() * 2.2;
      nos.push({
        x: Math.random() * l,
        y: Math.random() * a,
        // Deslocamento base guardado a parte: a repulsao do cursor e temporaria
        // e o no precisa saber para onde voltar.
        ox: 0, oy: 0,
        raio,
        cor: sortearCor(),
        fase: Math.random() * Math.PI * 2,
        // Velocidades minusculas e irracionais entre si: o padrao nunca repete.
        vx: (Math.random() - 0.5) * 0.16,
        vy: (Math.random() - 0.5) * 0.16,
        brilho: raio > 2.4,
      });
    }
    pulsos = [];
  }

  function corAlfa(hex, alfa) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alfa})`;
  }

  /* ------------------------------------------------------------ pulsos -- */

  function talvezPulso(ligacoes) {
    if (REDUZIR || pulsos.length > 14 || !ligacoes.length) return;
    if (Math.random() > 0.09) return;

    // So ligacoes que apontam para a direita: o fluxo tem sentido, como o
    // pipeline. Pulso indo para tras contaria a historia errada.
    const candidatas = ligacoes.filter(([i, j]) => nos[j].x > nos[i].x);
    if (!candidatas.length) return;

    const [i, j] = candidatas[(Math.random() * candidatas.length) | 0];
    pulsos.push({ de: i, para: j, t: 0, velocidade: 0.006 + Math.random() * 0.010, cor: nos[j].cor });
  }

  function desenharPulsos() {
    for (let k = pulsos.length - 1; k >= 0; k--) {
      const p = pulsos[k];
      p.t += p.velocidade;
      if (p.t >= 1) { pulsos.splice(k, 1); continue; }

      const de = nos[p.de], para = nos[p.para];
      if (!de || !para) { pulsos.splice(k, 1); continue; }

      const x = de.x + de.ox + (para.x + para.ox - de.x - de.ox) * p.t;
      const y = de.y + de.oy + (para.y + para.oy - de.y - de.oy) * p.t;
      // Aparece e some nas pontas: nada surge nem morre bruscamente.
      const forca = Math.sin(p.t * Math.PI);

      const halo = ctx.createRadialGradient(x, y, 0, x, y, 9);
      halo.addColorStop(0, corAlfa(p.cor, 0.75 * forca));
      halo.addColorStop(1, corAlfa(p.cor, 0));
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(x, y, 9, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = corAlfa("#FFFFFF", 0.9 * forca);
      ctx.beginPath();
      ctx.arc(x, y, 1.6, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  /* ----------------------------------------------------------- desenho -- */

  function passo() {
    ctx.clearRect(0, 0, l, a);

    for (const no of nos) {
      if (!REDUZIR) {
        no.x += no.vx;
        no.y += no.vy;
        // Rebate nas bordas em vez de teleportar: no atravessando a tela
        // quebra a continuidade das ligacoes.
        if (no.x < 0 || no.x > l) no.vx *= -1;
        if (no.y < 0 || no.y > a) no.vy *= -1;
      }

      const dx = no.x - cursor.x;
      const dy = no.y - cursor.y;
      const distancia = Math.hypot(dx, dy);
      if (distancia < RAIO_CURSOR && distancia > 0.1) {
        const forca = (1 - distancia / RAIO_CURSOR) ** 2 * 34;
        no.ox += ((dx / distancia) * forca - no.ox) * 0.12;
        no.oy += ((dy / distancia) * forca - no.oy) * 0.12;
      } else {
        no.ox += -no.ox * 0.07;
        no.oy += -no.oy * 0.07;
      }
    }

    // Ligacoes por proximidade. O alfa cai com o quadrado da distancia: a
    // ligacao some suave em vez de piscar ao cruzar o limite.
    const ligacoes = [];
    for (let i = 0; i < nos.length; i++) {
      const a1 = nos[i];
      const x1 = a1.x + a1.ox, y1 = a1.y + a1.oy;
      for (let j = i + 1; j < nos.length; j++) {
        const b1 = nos[j];
        const x2 = b1.x + b1.ox, y2 = b1.y + b1.oy;
        const d = Math.hypot(x2 - x1, y2 - y1);
        if (d > DISTANCIA_LIGACAO) continue;

        ligacoes.push([i, j]);
        const proximidade = 1 - d / DISTANCIA_LIGACAO;
        ctx.strokeStyle = corAlfa(a1.cor, proximidade * proximidade * 0.34);
        ctx.lineWidth = 0.65;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }
    }

    for (const no of nos) {
      const x = no.x + no.ox, y = no.y + no.oy;
      const cintila = no.brilho && !REDUZIR
        ? 0.65 + Math.sin(tempo * 0.0013 + no.fase) * 0.35
        : 1;

      if (no.brilho) {
        const halo = ctx.createRadialGradient(x, y, 0, x, y, no.raio * 7);
        halo.addColorStop(0, corAlfa(no.cor, 0.30 * cintila));
        halo.addColorStop(1, corAlfa(no.cor, 0));
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(x, y, no.raio * 7, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.fillStyle = corAlfa(no.cor, 0.9 * cintila);
      ctx.beginPath();
      ctx.arc(x, y, no.raio, 0, Math.PI * 2);
      ctx.fill();
    }

    talvezPulso(ligacoes);
    desenharPulsos();
  }

  function laco(agora) {
    tempo = agora;
    passo();
    requestAnimationFrame(laco);
  }

  canvas.addEventListener("mousemove", (ev) => {
    const caixa = canvas.getBoundingClientRect();
    cursor = { x: ev.clientX - caixa.left, y: ev.clientY - caixa.top };
  });
  canvas.addEventListener("mouseleave", () => { cursor = { x: -9999, y: -9999 }; });

  window.addEventListener("resize", dimensionar);
  dimensionar();
  requestAnimationFrame(laco);
})();
