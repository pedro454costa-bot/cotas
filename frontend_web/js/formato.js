/* Formatacao compartilhada. Nada de logica de negocio aqui. */

const Formato = {
  cnpj(valor) {
    const d = (valor || "").replace(/\D/g, "");
    if (d.length !== 14) return valor || "";
    return `${d.slice(0,2)}.${d.slice(2,5)}.${d.slice(5,8)}/${d.slice(8,12)}-${d.slice(12)}`;
  },

  dinheiro(valor) {
    if (valor === null || valor === undefined) return "—";
    // Acima de um milhao a tela ganha em legibilidade com a escala abreviada:
    // "R$ 1,2 bi" e mais rapido de ler que o numero cheio numa celula estreita.
    const abs = Math.abs(valor);
    if (abs >= 1e9) return `R$ ${(valor / 1e9).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} bi`;
    if (abs >= 1e6) return `R$ ${(valor / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mi`;
    return valor.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
  },

  percentual(valor, casas = 1) {
    if (valor === null || valor === undefined) return "—";
    return `${Number(valor).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas })}%`;
  },

  data(valor) {
    if (!valor) return "—";
    const iso = String(valor).slice(0, 10);
    const [a, m, d] = iso.split("-");
    return d ? `${d}/${m}/${a}` : iso;
  },

  periodo(inicio, fim) {
    const ate = fim ? Formato.data(fim) : "atual";
    return `${Formato.data(inicio)} → ${ate}`;
  },

  risco(valor) {
    return { ALTO: "Alto risco", MEDIO: "Risco médio", BAIXO: "Sem apontamento" }[valor]
        || "Não analisado";
  },

  classeRisco(valor) {
    return { ALTO: "alto", MEDIO: "medio", BAIXO: "baixo" }[valor] || "neutro";
  },

  manifestacao(valor) {
    return {
      SEM_RESSALVA: "Sem ressalva",
      ENCERRAMENTO: "Encerramento do fundo",
      ENFASE_OUTROS: "Ênfase / outros assuntos",
      CONTINUIDADE: "Continuidade operacional",
      RESSALVA: "Opinião com ressalva",
      ADVERSA: "Opinião adversa",
      ABSTENCAO: "Abstenção de opinião",
      INDETERMINADO: "Indeterminado",
    }[valor] || (valor || "—");
  },

  /* Todo texto vindo do banco passa por aqui antes de virar HTML. */
  escapar(texto) {
    if (texto === null || texto === undefined) return "";
    return String(texto)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
  },

  encurtar(texto, limite) {
    const t = String(texto || "");
    return t.length <= limite ? t : t.slice(0, limite - 1).trimEnd() + "…";
  },

  sigla(nome) {
    const palavras = String(nome || "").trim().split(/\s+/).filter(p => p.length > 2);
    return (palavras.slice(0, 2).map(p => p[0]).join("") || "—").toUpperCase();
  },
};
