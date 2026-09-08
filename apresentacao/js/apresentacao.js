/* Navegacao, revelacao dos slides e contadores. */

(() => {
  const slides = [...document.querySelectorAll(".slide")];
  const barra = document.getElementById("progresso");
  const pontos = document.getElementById("pontos");

  /* ------------------------------------------------ pontos de navegacao -- */

  slides.forEach((slide, i) => {
    const botao = document.createElement("button");
    botao.dataset.rotulo = slide.dataset.titulo || `Slide ${i + 1}`;
    botao.setAttribute("aria-label", botao.dataset.rotulo);
    botao.addEventListener("click", () => irPara(i));
    pontos.appendChild(botao);
  });
  const botoes = [...pontos.children];

  function irPara(indice) {
    const alvo = slides[Math.max(0, Math.min(indice, slides.length - 1))];
    if (alvo) alvo.scrollIntoView({ behavior: "smooth" });
  }

  function slideAtual() {
    const meio = window.scrollY + window.innerHeight / 2;
    return slides.findIndex((s) => s.offsetTop <= meio && s.offsetTop + s.offsetHeight > meio);
  }

  /* --------------------------------------------------------- contadores -- */

  /* Anima de 0 ate o valor. easeOutExpo desacelera bem no fim: o numero
     "aterrissa" no valor final em vez de parar seco. */
  function contar(elemento) {
    if (elemento.dataset.contado) return;
    elemento.dataset.contado = "1";

    const alvo = Number(elemento.dataset.contar);
    const prefixo = elemento.dataset.prefixo || "";
    const sufixo = elemento.dataset.sufixo || "";
    const duracao = 1500;
    const inicio = performance.now();

    function passo(agora) {
      const t = Math.min((agora - inicio) / duracao, 1);
      const suave = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
      const valor = Math.round(alvo * suave);
      elemento.textContent = prefixo + valor.toLocaleString("pt-BR") + sufixo;
      if (t < 1) requestAnimationFrame(passo);
    }
    requestAnimationFrame(passo);
  }

  /* ------------------------------------------------------- revelacao ---- */

  const observador = new IntersectionObserver((entradas) => {
    for (const entrada of entradas) {
      if (!entrada.isIntersecting) continue;
      entrada.target.classList.add("visivel");
      // Os contadores so disparam depois da entrada do bloco, senao o numero
      // termina de rodar antes de o elemento aparecer.
      setTimeout(() => {
        entrada.target.querySelectorAll("[data-contar]").forEach(contar);
      }, 380);
    }
  }, { threshold: 0.28 });

  slides.forEach((slide) => observador.observe(slide));

  /* ------------------------------------------------ progresso e teclado -- */

  /* A galaxia existe so nos slides marcados com data-morph. Fora deles o
     canvas apaga - manter 1.500 particulas desenhando atras de um slide de
     texto seria desperdicio de CPU e ruido visual. */
  const galaxia = document.getElementById("galaxia");

  function atualizarGalaxia(indice) {
    const slide = slides[indice];
    const modo = slide && slide.dataset.morph;
    const ativa = modo !== undefined && modo !== null;

    galaxia.classList.toggle("aceso", ativa);
    document.body.classList.toggle("modo-astro", ativa);

    if (ativa && window.RiskMapGalaxia) {
      window.RiskMapGalaxia.irPara(Number(modo));
    }
  }

  let ultimoSlide = -1;

  function atualizar() {
    const total = document.body.scrollHeight - window.innerHeight;
    barra.style.width = `${(window.scrollY / Math.max(total, 1)) * 100}%`;

    const atual = slideAtual();
    botoes.forEach((b, i) => b.classList.toggle("ativo", i === atual));

    if (atual !== ultimoSlide) {
      ultimoSlide = atual;
      atualizarGalaxia(atual);
    }
  }

  window.addEventListener("scroll", atualizar, { passive: true });
  window.addEventListener("resize", atualizar);
  atualizar();

  document.addEventListener("keydown", (ev) => {
    const atual = slideAtual();
    const teclas = {
      ArrowDown: 1, PageDown: 1, " ": 1, ArrowRight: 1,
      ArrowUp: -1, PageUp: -1, ArrowLeft: -1,
    };
    if (ev.key in teclas) {
      ev.preventDefault();
      irPara(atual + teclas[ev.key]);
    } else if (ev.key === "Home") {
      ev.preventDefault(); irPara(0);
    } else if (ev.key === "End") {
      ev.preventDefault(); irPara(slides.length - 1);
    } else if (ev.key === "f" || ev.key === "F") {
      // Apresentar em tela cheia sem precisar da barra do navegador.
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen?.();
    }
  });
})();
