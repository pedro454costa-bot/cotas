/* Miniatura viva do grafo de risco, no slide da interface.

   Nao e captura de tela: e o mesmo conceito visual do sistema real, redesenhado
   em canvas com dados ilustrativos. Assim a apresentacao mostra o comportamento
   - o no de risco alto pulsando - que uma imagem estatica nao transmite.
*/

(() => {
  const canvas = document.getElementById("demo-grafo");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const REDUZIR = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const CORES = {
    alto:  "#FF5A6E",
    medio: "#FFB020",
    baixo: "#31D0AA",
    raiz:  "#FFFFFF",
    nulo:  "#5A6575",
  };

  // Posicoes em fracao da area, para o layout acompanhar o redimensionamento.
  const NOS = [
    { x: .50, y: .50, r: 20, tipo: "raiz",  rotulo: "FUNDO ANALISADO" },
    { x: .24, y: .28, r: 13, tipo: "alto",  rotulo: "Cadeia com ressalva" },
    { x: .76, y: .26, r: 10, tipo: "medio", rotulo: "Ativo iliquido" },
    { x: .19, y: .70, r: 11, tipo: "baixo", rotulo: "Sem apontamento" },
    { x: .78, y: .72, r: 14, tipo: "alto",  rotulo: "Abstencao de opiniao" },
    { x: .50, y: .84, r: 8,  tipo: "nulo",  rotulo: "Nao analisado" },
    { x: .38, y: .13, r: 7,  tipo: "baixo", rotulo: "" },
    { x: .90, y: .48, r: 6,  tipo: "nulo",  rotulo: "" },
  ];

  const ARESTAS = [[0,1],[0,2],[0,3],[0,4],[0,5],[1,6],[4,7]];

  let l = 0, a = 0, dpr = 1, tempo = 0;

  function dimensionar() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const caixa = canvas.getBoundingClientRect();
    l = caixa.width; a = caixa.height;
    canvas.width = l * dpr;
    canvas.height = a * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function corAlfa(hex, alfa) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alfa})`;
  }

  function ponto(no) {
    // Respiracao minima: o grafo nunca fica completamente parado.
    const respira = REDUZIR ? 0 : Math.sin(tempo * 0.0006 + no.x * 9) * 3;
    return { x: no.x * l, y: no.y * a + respira };
  }

  function desenhar() {
    ctx.clearRect(0, 0, l, a);

    // Arestas primeiro, sempre por baixo dos nos.
    for (const [i, j] of ARESTAS) {
      const p1 = ponto(NOS[i]);
      const p2 = ponto(NOS[j]);
      const critico = NOS[j].tipo === "alto";
      ctx.strokeStyle = corAlfa(critico ? CORES.alto : "#5A6575", critico ? .5 : .26);
      ctx.lineWidth = critico ? 1.5 : 1;
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      // Curva leve: linha reta entre nos deixa o desenho duro.
      const cx = (p1.x + p2.x) / 2 + (p2.y - p1.y) * 0.12;
      const cy = (p1.y + p2.y) / 2 - (p2.x - p1.x) * 0.12;
      ctx.quadraticCurveTo(cx, cy, p2.x, p2.y);
      ctx.stroke();
    }

    for (const no of NOS) {
      const p = ponto(no);
      const cor = CORES[no.tipo];

      // Ondas de alerta: so em risco alto, como no sistema real.
      if (no.tipo === "alto" && !REDUZIR) {
        for (let k = 0; k < 3; k++) {
          const avanco = ((tempo / 2400) + k / 3) % 1;
          const opacidade = Math.pow(1 - avanco, 3) * .5;
          if (opacidade < .01) continue;
          ctx.strokeStyle = corAlfa(cor, opacidade);
          ctx.lineWidth = Math.max(2 * (1 - avanco), .5);
          ctx.beginPath();
          ctx.arc(p.x, p.y, no.r * (1 + avanco * 2.6), 0, Math.PI * 2);
          ctx.stroke();
        }
      }

      const halo = ctx.createRadialGradient(p.x, p.y, no.r * .5, p.x, p.y, no.r * 3.2);
      halo.addColorStop(0, corAlfa(cor, .42));
      halo.addColorStop(1, corAlfa(cor, 0));
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(p.x, p.y, no.r * 3.2, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = corAlfa(cor, .92);
      ctx.beginPath();
      ctx.arc(p.x, p.y, no.r, 0, Math.PI * 2);
      ctx.fill();

      ctx.strokeStyle = corAlfa("#FFFFFF", no.tipo === "raiz" ? .6 : .2);
      ctx.lineWidth = no.tipo === "raiz" ? 2 : 1;
      ctx.beginPath();
      ctx.arc(p.x, p.y, no.r + 1.5, 0, Math.PI * 2);
      ctx.stroke();

      if (no.rotulo) {
        ctx.font = `${no.tipo === "raiz" ? 600 : 400} ${no.tipo === "raiz" ? 11 : 10}px "Segoe UI", sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = corAlfa(no.tipo === "raiz" ? "#FFFFFF" : cor, .8);
        ctx.fillText(no.rotulo, p.x, p.y + no.r + 8);
      }
    }
  }

  function laco(agora) {
    tempo = agora;
    desenhar();
    requestAnimationFrame(laco);
  }

  window.addEventListener("resize", dimensionar);
  dimensionar();
  requestAnimationFrame(laco);
})();
