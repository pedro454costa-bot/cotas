/* Camada unica de acesso a API. Nenhum outro arquivo faz fetch. */

const API = (() => {
  async function pegar(rota) {
    const resposta = await fetch(rota, { headers: { Accept: "application/json" } });
    if (!resposta.ok) {
      let detalhe = `Erro ${resposta.status}`;
      try { detalhe = (await resposta.json()).detail || detalhe; } catch (_) {}
      const erro = new Error(detalhe);
      erro.status = resposta.status;
      throw erro;
    }
    return resposta.json();
  }

  async function enviar(rota, metodo, corpo) {
    const resposta = await fetch(rota, {
      method: metodo,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    });
    if (!resposta.ok) throw new Error(`Erro ${resposta.status}`);
    return resposta.json();
  }

  return {
    exemplos:      ()      => pegar("/api/exemplos"),
    constelacao:   ()      => pegar("/api/constelacao"),
    buscar:        (termo) => pegar(`/api/busca?q=${encodeURIComponent(termo)}`),
    fundo:         (cnpj)  => pegar(`/api/fundos/${cnpj}`),
    grafo:         (cnpj, p = 1) => pegar(`/api/fundos/${cnpj}/grafo?profundidade=${p}`),
    demonstracoes: (cnpj)  => pegar(`/api/fundos/${cnpj}/demonstracoes`),
    riscoCadeia:   (cnpj)  => pegar(`/api/fundos/${cnpj}/risco-cadeia`),
    indicadores:   ()      => pegar("/api/monitoramento/indicadores"),
    monitoramento: (filtros) => pegar("/api/monitoramento?" + new URLSearchParams(filtros)),
    listaNegativa: ()      => pegar("/api/lista-negativa"),
    mudarStatus:   (id, status) => enviar(`/api/monitoramento/${id}/status`, "PUT", { status }),
  };
})();
