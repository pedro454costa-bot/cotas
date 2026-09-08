/* Interacao da maquete: abrir e fechar a analise da DF.

   E o unico ponto interativo da apresentacao, e existe por um motivo: contar
   que "a IA escreve a analise" e uma coisa; deixar a pessoa clicar e ver o
   texto aparecer e outra. O clique acontece dentro da moldura, entao quem
   assiste entende que e a tela do sistema reagindo.
*/

(() => {
  const cartao = document.getElementById("df-ressalva");
  const gaveta = document.getElementById("mock-gaveta");
  const fundo = document.getElementById("mock-fundo");
  const fechar = document.getElementById("mock-fechar");
  if (!cartao || !gaveta) return;

  function abrir() {
    gaveta.hidden = false;
    fundo.hidden = false;
  }

  function esconder() {
    gaveta.hidden = true;
    fundo.hidden = true;
  }

  cartao.addEventListener("click", abrir);
  cartao.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); abrir(); }
  });

  fechar.addEventListener("click", esconder);
  fundo.addEventListener("click", esconder);
  // Escape ja e usado pela navegacao do deck, mas aqui a gaveta tem prioridade.
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !gaveta.hidden) { ev.stopPropagation(); esconder(); }
  }, true);
})();
