// Cliente da API: caminhos relativos, JSON de volta, Error com o "detail" da API.
async function chamar(metodo, caminho, corpo) {
  const opcoes = { method: metodo, headers: {} };
  if (corpo !== undefined) {
    opcoes.headers["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }
  const resp = await fetch(caminho, opcoes);
  if (!resp.ok) {
    let msg = `Erro ${resp.status}`;
    try {
      const d = (await resp.json()).detail;
      if (d) msg = typeof d === "string" ? d : JSON.stringify(d);
    } catch (_) { /* resposta sem JSON */ }
    throw new Error(msg);
  }
  return resp.status === 204 ? null : resp.json();
}

export const api = {
  get: (caminho) => chamar("GET", caminho),
  post: (caminho, corpo) => chamar("POST", caminho, corpo),
  put: (caminho, corpo) => chamar("PUT", caminho, corpo),
  del: (caminho) => chamar("DELETE", caminho),
};
