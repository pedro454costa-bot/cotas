/* Constelacao: todos os fundos como pontos, na tela de entrada.

   Canvas proprio, sem vis-network. Sao milhares de pontos e o vis-network
   gerencia fisica, arestas, eventos e hit-testing por no - custo que nao se
   paga aqui, onde nao ha aresta nenhuma e o desenho e um circulo. Em canvas
   cru, 6 mil pontos animam a 60fps sem esforco.

   O layout agrupa por CLASSE do fundo. Distribuicao aleatoria daria uma nuvem
   bonita e muda; agrupada, a imagem passa a dizer algo - da para ver que os
   multimercados sao um continente e os FIDCs uma ilha, e onde o vermelho se
   concentra.
*/

const Constelacao = (() => {
  const CORES = {
    ALTO:  "#FF4D5E",
    MEDIO: "#FFB020",
    BAIXO: "#31D0AA",
    NULO:  "#5A6575",
  };

  let canvas = null;
  let ctx = null;
  let pontos = [];
  let animacao = null;
  let tempo = 0;
  let mouse = { x: -1e6, y: -1e6 };
  let sobre = null;
  let aoClicar = () => {};
  let dpr = 1;

  const REDUZIR_MOVIMENTO =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------------- layout */

  /* Hash estavel do CNPJ: a posicao de cada fundo precisa ser a mesma a cada
     carregamento. Com Math.random() o mesmo fundo pularia de lugar e o usuario
     perderia a referencia espacial que acabou de construir. */
  function embaralhar(texto) {
    let h = 2166136261;
    for (let i = 0; i < texto.length; i++) {
      h ^= texto.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return ((h >>> 0) % 100000) / 100000;
  }

  function centrosPorClasse(dados) {
    const classes = [...new Set(dados.map((d) => d.classe || "—"))];
    const centros = new Map();
    const dourado = Math.PI * (3 - Math.sqrt(5));   // espiral de filotaxia

    classes.forEach((classe, i) => {
      // Espiral distribui os centros com densidade uniforme, sem o padrao de
      // grade que um layout circular simples produz.
      const raio = Math.sqrt((i + 0.6) / classes.length) * 0.82;
      const angulo = i * dourado;
      centros.set(classe, { x: Math.cos(angulo) * raio, y: Math.sin(angulo) * raio });
    });
    return centros;
  }

  function montarPontos(dados) {
    const centros = centrosPorClasse(dados);

    return dados.map((fundo) => {
      const centro = centros.get(fundo.classe || "—");
      const a = embaralhar(fundo.cnpj);
      const b = embaralhar(fundo.cnpj + "y");
      const angulo = a * Math.PI * 2;
      // Raiz quadrada da dispersao: sem ela os pontos ficam em anel, com um
      // vazio no meio de cada aglomerado.
      const dispersao = Math.sqrt(b) * 0.2;

      const risco = fundo.classificacao_risco;
      return {
        cnpj: fundo.cnpj,
        nome: fundo.nome,
        classe: fundo.classe,
        risco,
        cor: CORES[risco] || CORES.NULO,
        // Ponto com risco e maior: o olho vai para o que importa.
        raio: risco === "ALTO" ? 2.9 : risco === "MEDIO" ? 2.2 : risco === "BAIXO" ? 1.9 : 1.2,
        brilha: risco === "ALTO" || risco === "MEDIO",
        bx: centro.x + Math.cos(angulo) * dispersao,
        by: centro.y + Math.sin(angulo) * dispersao,
        fase: a * Math.PI * 2,
        velocidade: 0.25 + b * 0.5,
        x: 0, y: 0,
      };
    });
  }

  /* --------------------------------------------------------------- desenho */

  function dimensionar() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const caixa = canvas.getBoundingClientRect();
    canvas.width = caixa.width * dpr;
    canvas.height = caixa.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function desenhar() {
    const l = canvas.width / dpr;
    const a = canvas.height / dpr;
    const escala = Math.min(l, a) * 0.46;
    const cx = l / 2;
    const cy = a / 2;

    ctx.clearRect(0, 0, l, a);

    let maisProximo = null;
    let menorDistancia = 14 * 14;

    for (const p of pontos) {
      // Deriva lenta em orbita minuscula: o ceu respira sem que nada "ande".
      const desloc = REDUZIR_MOVIMENTO ? 0 : Math.sin(tempo * 0.00018 * p.velocidade + p.fase) * 0.006;
      p.x = cx + (p.bx + desloc) * escala;
      p.y = cy + (p.by - desloc * 0.7) * escala;

      const dx = p.x - mouse.x;
      const dy = p.y - mouse.y;
      const distancia = dx * dx + dy * dy;
      if (distancia < menorDistancia) { menorDistancia = distancia; maisProximo = p; }

      // Cintilacao so nos coloridos - poeira cinza parada faz o contraste.
      const cintila = p.brilha && !REDUZIR_MOVIMENTO
        ? 0.75 + Math.sin(tempo * 0.0016 * p.velocidade + p.fase) * 0.25
        : 1;

      if (p.brilha) {
        const halo = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.raio * 5);
        halo.addColorStop(0, corAlfa(p.cor, 0.32 * cintila));
        halo.addColorStop(1, corAlfa(p.cor, 0));
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.raio * 5, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.fillStyle = corAlfa(p.cor, (p.risco ? 0.95 : 0.5) * cintila);
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.raio, 0, Math.PI * 2);
      ctx.fill();
    }

    sobre = maisProximo;
    if (sobre) destacar(sobre);
  }

  function destacar(p) {
    ctx.strokeStyle = corAlfa("#FFFFFF", 0.8);
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.raio + 6, 0, Math.PI * 2);
    ctx.stroke();

    const texto = Formato.encurtar(p.nome || p.cnpj, 46);
    ctx.font = '600 12px "Segoe UI", sans-serif';
    const largura = ctx.measureText(texto).width;
    const bx = p.x + 12;
    const by = p.y - 30;

    ctx.fillStyle = "rgba(10,12,16,.92)";
    ctx.strokeStyle = corAlfa(p.cor, 0.5);
    ctx.lineWidth = 1;
    caixaArredondada(bx, by, largura + 20, 40, 7);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#FFFFFF";
    ctx.fillText(texto, bx + 10, by + 17);
    ctx.font = '400 10.5px "Segoe UI", sans-serif';
    ctx.fillStyle = corAlfa(p.cor, 0.95);
    ctx.fillText(`${Formato.risco(p.risco)} · ${p.classe || "—"}`, bx + 10, by + 31);
  }

  function caixaArredondada(x, y, l, a, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + l, y, x + l, y + a, r);
    ctx.arcTo(x + l, y + a, x, y + a, r);
    ctx.arcTo(x, y + a, x, y, r);
    ctx.arcTo(x, y, x + l, y, r);
    ctx.closePath();
  }

  function corAlfa(hex, alfa) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alfa})`;
  }

  /* ----------------------------------------------------------------- ciclo */

  function laco(agora) {
    tempo = agora;
    desenhar();
    animacao = requestAnimationFrame(laco);
  }

  function parar() {
    if (animacao !== null) { cancelAnimationFrame(animacao); animacao = null; }
  }

  async function iniciar(elementoCanvas, aoClicarFundo) {
    canvas = elementoCanvas;
    ctx = canvas.getContext("2d");
    aoClicar = aoClicarFundo || (() => {});

    const dados = await API.constelacao();
    pontos = montarPontos(dados);

    dimensionar();
    window.addEventListener("resize", dimensionar);

    canvas.addEventListener("mousemove", (ev) => {
      const caixa = canvas.getBoundingClientRect();
      mouse = { x: ev.clientX - caixa.left, y: ev.clientY - caixa.top };
      canvas.style.cursor = sobre ? "pointer" : "default";
    });
    canvas.addEventListener("mouseleave", () => { mouse = { x: -1e6, y: -1e6 }; });
    canvas.addEventListener("click", () => { if (sobre) aoClicar(sobre.cnpj); });

    parar();
    animacao = requestAnimationFrame(laco);
    return pontos.length;
  }

  return { iniciar, parar };
})();
