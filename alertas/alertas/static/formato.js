// Funções puras de formatação da interface (sem DOM, testáveis em Node).

const dois = (n) => String(n).padStart(2, "0");
const hhmm = (d) => `${dois(d.getHours())}:${dois(d.getMinutes())}`;
const inicioDoDia = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

export const TITULO_RESUMO = "Resumo diário";

export const ROTULOS = { grave: "Grave", normal: "Normal", info: "Info" };

// Dia de "d" em relação a "agora": "hoje", "ontem" ou "DD/MM".
export function diaRelativo(d, agora) {
  const dias = Math.round((inicioDoDia(agora) - inicioDoDia(d)) / 86400000);
  if (dias === 0) return "hoje";
  if (dias === 1) return "ontem";
  return `${dois(d.getDate())}/${dois(d.getMonth() + 1)}`;
}

// "quando" da lista e do detalhe: há N min / hoje, HH:MM / ontem, HH:MM / DD/MM, HH:MM.
export function quando(iso, agora = new Date()) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const min = Math.floor((agora - d) / 60000);
  if (min >= 0 && min < 60) return min === 0 ? "agora" : `há ${min} min`;
  return `${diaRelativo(d, agora)}, ${hhmm(d)}`;
}

export function contar(alertas) {
  const naoLidos = alertas.filter((a) => !a.lido);
  return { naoLidos: naoLidos.length, graves: naoLidos.filter((a) => a.gravidade === "grave").length };
}

// Subtítulo do cabeçalho: "N não lidos · M grave(s)" ou "Tudo em dia".
export function subtitulo(alertas) {
  const { naoLidos, graves } = contar(alertas);
  if (naoLidos === 0) return "Tudo em dia";
  let t = naoLidos === 1 ? "1 não lido" : `${naoLidos} não lidos`;
  if (graves > 0) t += graves === 1 ? " · 1 grave" : ` · ${graves} graves`;
  return t;
}

// Número final de "detalhes" (resumo diário); null se não houver.
export function numeroDoResumo(detalhes) {
  const m = /(\d+)\s*\.?\s*$/.exec(String(detalhes ?? ""));
  return m ? Number.parseInt(m[1], 10) : null;
}

export function ehResumo(a) {
  return a.gravidade === "info" && a.titulo === TITULO_RESUMO && numeroDoResumo(a.detalhes) !== null;
}

// "Últimas 24 horas, até hoje às 08:00"
export function periodoResumo(iso, agora = new Date()) {
  const d = new Date(iso);
  return `Últimas 24 horas, até ${diaRelativo(d, agora)} às ${hhmm(d)}`;
}

// A frase explicativa só vale para tentativas negadas.
export function temExplicacao(a) {
  return a.titulo.startsWith("Tentativa negada");
}

// Texto da frase explicativa ("" quando não se aplica). Só a 1ª linha dos detalhes
// ("ferramenta: <nome>") decide: as outras linhas trazem texto escolhido pelo cliente.
export function explicacao(a) {
  if (!temExplicacao(a)) return "";
  const ferramenta = (a.detalhes ?? "").split("\n")[0];
  if (ferramenta === "ferramenta: criar_nota") {
    return "Um cliente com token válido tentou gravar uma nota fora do que é permitido. Nada foi gravado.";
  }
  return "Um cliente com token válido pediu algo fora do que pode ler. Nada foi entregue.";
}

// base64url -> Uint8Array (applicationServerKey do push)
export function base64urlParaBytes(texto) {
  const b64 = texto.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (texto.length % 4)) % 4);
  const bin = atob(b64);
  const saida = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) saida[i] = bin.charCodeAt(i);
  return saida;
}

// Cabeçalho e estado vazio conforme o resultado do carregamento.
// "Tudo em dia" / "Nenhum alerta" só valem depois de um carregamento que deu certo.
export function cabecalho({ tentou, falhou, alertas }) {
  if (falhou) return { subtitulo: "Não foi possível carregar", mostrarVazia: false };
  if (!tentou) return { subtitulo: "", mostrarVazia: false };
  return { subtitulo: subtitulo(alertas), mostrarVazia: alertas.length === 0 };
}
