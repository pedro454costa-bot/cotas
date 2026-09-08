/* Galaxia espiral que se desfaz e vira o universo de fundos.

   Uma unica nuvem de particulas com DOIS destinos:

     forma 0  espiral logaritmica de dois bracos, nucleo denso, cores de estrela
     forma 1  aglomerados por classe de fundo, cores de risco

   A posicao de cada particula e a interpolacao entre os dois destinos, e a cor
   tambem interpola. Nao ha troca de cena: sao as MESMAS estrelas que viram
   fundos. E o argumento visual da apresentacao - o universo ja existia, o que
   mudou foi conseguir enxergar o que ha nele.

   O morph e disparado pelo slide ativo (nao pelo scroll bruto) e leva ~2,6s,
   com aceleracao no meio. Preso ao scroll ficaria travado no snap.
*/

(() => {
  const canvas = document.getElementById("galaxia");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const REDUZIR = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const TOTAL = 1500;
  const BRACOS = 2;
  const VOLTAS = 2.35;
  const DURACAO_MORPH = 2600;

  // Giro da galaxia. Com .00042 a volta completa levava ~13 minutos: correto
  // em escala astronomica, invisivel numa apresentacao. Aqui a particula do
  // nucleo fecha uma volta em ~1 minuto - da para PERCEBER o movimento sem
  // que a espiral vire um ventilador.
  const VELOCIDADE_ROTACAO = .0034;

  // Paleta de estrela: branco dominante, azuis e um toque quente - e a
  // distribuicao real de cor de uma galaxia espiral em imagem astronomica.
  const ESTRELA = [
    ["#FFFFFF", .40], ["#CFE2FF", .22], ["#9FC4FF", .14],
    ["#FFD9B0", .13], ["#FFB07A", .07], ["#8AA8FF", .04],
  ];

  // Paleta de risco, nas proporcoes reais da base analisada.
  const RISCO = [
    ["#FF5A6E", .25],   // alto    1.523
    ["#FFB020", .43],   // medio   2.564
    ["#31D0AA", .15],   // baixo     872
    ["#5A6575", .17],   // sem analise
  ];

  // Aglomerados = classes de fundo, com o peso real de cada uma.
  //
  // Todos ficam AFASTADOS DO CENTRO de proposito: o miolo da tela pertence ao
  // texto. Aglomerado no meio disputa leitura com o titulo e os dois perdem.
  // Os x sao amplos (ate 1.35) porque o slide e largo e a escala usa a menor
  // dimensao - sem isso os grupos se amontoam no centro em tela panoramica.
  const CLASSES = [
    { nome: "Multimercado", peso: .535, x: -1.05, y: -.30, raio: .30 },
    { nome: "Renda Fixa",   peso: .159, x: -1.18, y:  .42, raio: .19 },
    { nome: "Ações",        peso: .082, x:  1.10, y: -.38, raio: .17 },
    { nome: "FIC / Cotas",  peso: .146, x:  1.22, y:  .30, raio: .20 },
    { nome: "Outros",       peso: .078, x:  -.15, y:  .78, raio: .17 },
  ];

  let particulas = [];
  let l = 0, a = 0, dpr = 1, escala = 1, escalaX = 1;
  let tempo = 0, rotacao = 0;
  let morph = 0, alvoMorph = 0, inicioMorph = 0, deMorph = 0;

  /* ------------------------------------------------------------ apoio -- */

  function sortear(tabela) {
    let r = Math.random();
    for (const [valor, peso] of tabela) {
      r -= peso;
      if (r <= 0) return valor;
    }
    return tabela[0][0];
  }

  function rgb(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function misturar(c1, c2, t) {
    return `rgba(${Math.round(c1[0] + (c2[0] - c1[0]) * t)},${Math.round(c1[1] + (c2[1] - c1[1]) * t)},${Math.round(c1[2] + (c2[2] - c1[2]) * t)},`;
  }

  /* -------------------------------------------------------- geometria -- */

  /* Espiral logaritmica: o angulo cresce e o raio cresce exponencialmente com
     ele. A dispersao diminui perto do centro, o que produz o nucleo denso. */
  function posicaoEspiral(i) {
    const t = i / TOTAL;
    // Concentra particulas no centro: t^1.7 empurra a maioria para raio baixo.
    const avanco = Math.pow(Math.random(), 1.7);
    const braco = i % BRACOS;
    const angulo = avanco * VOLTAS * Math.PI * 2 + (braco / BRACOS) * Math.PI * 2;
    const raio = avanco * .92;

    // Dispersao perpendicular ao braco, proporcional ao raio: braco fino no
    // centro e aberto na ponta, como galaxia de verdade.
    const espalha = (Math.random() - .5) * (.055 + avanco * .16);
    const espalhaR = (Math.random() - .5) * .05;

    return {
      raio: raio + espalhaR,
      angulo: angulo + espalha / Math.max(raio, .12),
      avanco,
    };
  }

  function posicaoAglomerado() {
    let r = Math.random();
    let classe = CLASSES[CLASSES.length - 1];
    for (const c of CLASSES) {
      r -= c.peso;
      if (r <= 0) { classe = c; break; }
    }
    const angulo = Math.random() * Math.PI * 2;
    // Raiz quadrada distribui por area: sem ela os pontos formam um anel.
    const d = Math.sqrt(Math.random()) * classe.raio;
    return { x: classe.x + Math.cos(angulo) * d, y: classe.y + Math.sin(angulo) * d };
  }

  function dimensionar() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const caixa = canvas.getBoundingClientRect();
    l = caixa.width; a = caixa.height;
    canvas.width = l * dpr;
    canvas.height = a * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    escala = Math.min(l, a) * .46;
    // Na forma de aglomerados o desenho se espalha na horizontal, entao o eixo
    // x ganha escala propria. Na espiral os dois eixos continuam iguais, para
    // a galaxia nao sair achatada.
    escalaX = Math.max(escala, l * .30);
  }

  function gerar() {
    particulas = [];
    for (let i = 0; i < TOTAL; i++) {
      const esp = posicaoEspiral(i);
      const agl = posicaoAglomerado();
      const brilhante = Math.random() < .07;

      particulas.push({
        raio: esp.raio, angulo: esp.angulo, avanco: esp.avanco,
        ax: agl.x, ay: agl.y,
        corEstrela: rgb(sortear(ESTRELA)),
        corRisco: rgb(sortear(RISCO)),
        // Particula do nucleo e menor e mais densa; das pontas, maior.
        tamanho: (brilhante ? 1.5 : .55) + Math.random() * (.5 + esp.avanco * 1.3),
        brilhante,
        fase: Math.random() * Math.PI * 2,
        // Rotacao diferencial: o centro gira mais rapido que a borda, como
        // numa galaxia real. E o que faz os bracos "enrolarem" com o tempo.
        velocidade: .10 + (1 - esp.avanco) * .22,
      });
    }
  }

  /* --------------------------------------------------------- desenho -- */

  function suavizar(t) {
    // easeInOutCubic: sai devagar, acelera no meio, chega devagar.
    return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  function desenhar() {
    ctx.clearRect(0, 0, l, a);
    const cx = l / 2, cy = a / 2;
    const m = morph;

    // Nucleo: so existe na forma galaxia, some conforme as particulas migram.
    if (m < .98) {
      const forca = (1 - m) ** 2;
      const nucleo = ctx.createRadialGradient(cx, cy, 0, cx, cy, escala * .42);
      nucleo.addColorStop(0,   `rgba(255,252,244,${.60 * forca})`);
      nucleo.addColorStop(.14, `rgba(255,238,214,${.28 * forca})`);
      nucleo.addColorStop(.42, `rgba(180,190,235,${.09 * forca})`);
      nucleo.addColorStop(1,   "rgba(120,140,220,0)");
      ctx.fillStyle = nucleo;
      ctx.beginPath();
      ctx.arc(cx, cy, escala * .42, 0, Math.PI * 2);
      ctx.fill();
    }

    for (const p of particulas) {
      const ang = p.angulo + rotacao * p.velocidade;
      const ex = Math.cos(ang) * p.raio;
      const ey = Math.sin(ang) * p.raio * .82;   // achatamento: galaxia inclinada

      // O eixo x interpola tambem a ESCALA: espiral usa a escala uniforme,
      // aglomerado usa a horizontal, mais larga.
      const escX = escala + (escalaX - escala) * m;
      const x = cx + (ex * escala + (p.ax * escX - ex * escala) * m);
      const y = cy + (ey + (p.ay - ey) * m) * escala;

      const cintila = p.brilhante && !REDUZIR
        ? .62 + Math.sin(tempo * .0016 + p.fase) * .38
        : 1;
      // Particula do nucleo brilha mais que a da ponta - so na forma galaxia.
      const brilhoRaio = 1 - p.avanco * .45;
      const alfa = (.30 + brilhoRaio * .55) * cintila * (1 - m * .18);

      const base = misturar(p.corEstrela, p.corRisco, m);
      const tamanho = p.tamanho * (1 + m * .35);

      if (p.brilhante || tamanho > 1.7) {
        const halo = ctx.createRadialGradient(x, y, 0, x, y, tamanho * 7);
        halo.addColorStop(0, base + (.34 * cintila) + ")");
        halo.addColorStop(1, base + "0)");
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(x, y, tamanho * 7, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.fillStyle = base + alfa + ")";
      ctx.beginPath();
      ctx.arc(x, y, tamanho, 0, Math.PI * 2);
      ctx.fill();

      // Espiculas de difracao nas mais brilhantes: e o detalhe que faz o
      // conjunto parecer foto astronomica em vez de pontos num canvas.
      if (p.brilhante && cintila > .82) {
        const braco = tamanho * 6 * cintila;
        ctx.strokeStyle = base + (.24 * cintila) + ")";
        ctx.lineWidth = .7;
        ctx.beginPath();
        ctx.moveTo(x - braco, y); ctx.lineTo(x + braco, y);
        ctx.moveTo(x, y - braco); ctx.lineTo(x, y + braco);
        ctx.stroke();
      }
    }
  }

  /* ----------------------------------------------------------- ciclo -- */

  function laco(agora) {
    tempo = agora;
    if (!REDUZIR) rotacao += VELOCIDADE_ROTACAO;

    if (morph !== alvoMorph) {
      const t = Math.min((agora - inicioMorph) / DURACAO_MORPH, 1);
      morph = deMorph + (alvoMorph - deMorph) * suavizar(t);
      if (t >= 1) morph = alvoMorph;
    }

    desenhar();
    requestAnimationFrame(laco);
  }

  /* Chamado pela navegacao: 0 = galaxia, 1 = universo de fundos. */
  window.RiskMapGalaxia = {
    irPara(valor) {
      if (alvoMorph === valor) return;
      deMorph = morph;
      alvoMorph = valor;
      inicioMorph = performance.now();
    },
  };

  window.addEventListener("resize", () => { dimensionar(); });
  dimensionar();
  gerar();
  requestAnimationFrame(laco);
})();
