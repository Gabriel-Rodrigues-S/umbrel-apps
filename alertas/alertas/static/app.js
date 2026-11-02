// Interface do app de alertas. Todo dado vindo da API entra na página por textContent:
// nada de HTML montado a partir de texto (titulo/detalhes podem ter texto de terceiros).
import {
  ROTULOS, base64urlParaBytes, cabecalho, contar, ehResumo, numeroDoResumo, explicacao, periodoResumo, quando, subtitulo, temExplicacao,
} from "./formato.js";

const CHAVE_DISPENSADO = "alertas.notificacoes.dispensado";
const ATUALIZAR_A_CADA_MS = 60000;

const PC = window.matchMedia("(min-width: 900px)");
const $ = (id) => document.getElementById(id);
const estado = { alertas: [], tentou: false, falhou: false, notificacoes: false };

// ---------- API ----------

async function carregar() {
  try {
    const r = await fetch("/api/alertas", { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(String(r.status));
    estado.alertas = await r.json();
    estado.falhou = false;
  } catch {
    estado.falhou = true;
  }
  estado.tentou = true;
  desenhar();
}

async function marcarLido(a, botoes) {
  for (const b of botoes) b.disabled = true;
  try {
    const r = await fetch(`/api/alertas/${encodeURIComponent(a.id)}/lido`, { method: "POST" });
    if (r.ok) a.lido = true;
  } catch {
    /* sem rede: o botão volta e dá para tentar de novo */
  }
  for (const b of botoes) b.disabled = false;
  desenhar();
}

// ---------- rotas (hash) ----------

function idDaRota() {
  const m = /^#\/alerta\/(\d+)$/.exec(location.hash);
  return m ? Number(m[1]) : null;
}

function alertaSelecionado() {
  const id = idDaRota();
  const pedido = id === null ? null : estado.alertas.find((a) => a.id === id) ?? null;
  // No PC o painel da direita mostra o primeiro item quando nada foi escolhido.
  return { pedido, painel: pedido ?? estado.alertas[0] ?? null };
}

// ---------- desenho ----------

function desenhar() {
  const app = $("app");
  const { pedido, painel } = alertaSelecionado();
  app.dataset.vista = estado.notificacoes ? "notif" : pedido ? "detalhe" : "lista";

  const { naoLidos } = contar(estado.alertas);
  const cab = cabecalho(estado);
  $("subtitulo").textContent = cab.subtitulo;
  const contador = $("contador");
  contador.hidden = naoLidos === 0;
  contador.textContent = String(naoLidos);

  desenharLista(painel);
  desenharDetalhe(painel);
}

function desenharLista(selecionado) {
  const agora = new Date();
  const modelo = $("modelo-item");
  const itens = estado.alertas.map((a) => {
    const el = modelo.content.firstElementChild.cloneNode(true);
    el.href = `#/alerta/${a.id}`;
    el.classList.toggle("lido", a.lido);
    if (selecionado && selecionado.id === a.id && (idDaRota() !== null || PC.matches)) el.setAttribute("aria-current", "true");
    const selo = el.querySelector(".selo");
    selo.classList.add(`selo-${a.gravidade}`);
    el.querySelector(".item-rotulo").textContent = ROTULOS[a.gravidade] ?? a.gravidade;
    el.querySelector(".item-quando").textContent = quando(a.criado_em, agora);
    el.querySelector(".item-texto").textContent = a.titulo;
    el.querySelector(".item-origem").textContent = a.origem;
    return el;
  });
  $("itens").replaceChildren(...itens);
  $("vazia").hidden = !cabecalho(estado).mostrarVazia;
}

function desenharDetalhe(a) {
  const normal = $("corpo-normal");
  const resumo = $("corpo-resumo");
  normal.hidden = resumo.hidden = true;
  if (!a) return;
  const agora = new Date();

  if (ehResumo(a)) {
    $("r-periodo").textContent = periodoResumo(a.criado_em, agora);
    $("r-numero").textContent = String(numeroDoResumo(a.detalhes));
    $("r-lido").hidden = a.lido;
    $("r-lido").onclick = () => marcarLido(a, [$("r-lido")]);
    resumo.hidden = false;
    return;
  }

  const selo = $("d-selo");
  selo.className = `selo selo-grande selo-${a.gravidade}`;
  $("d-rotulo").textContent = ROTULOS[a.gravidade] ?? a.gravidade;
  $("d-titulo").textContent = a.titulo;
  $("d-origem").textContent = a.origem;
  $("d-quando").textContent = quando(a.criado_em, agora);
  $("d-detalhes").textContent = a.detalhes;
  $("d-detalhes").hidden = !a.detalhes;
  $("d-detalhes").parentElement.hidden = !a.detalhes && !temExplicacao(a);
  $("d-explica").textContent = explicacao(a);
  $("d-explica").hidden = !temExplicacao(a);
  $("d-lido").hidden = a.lido;
  $("d-lido").onclick = () => marcarLido(a, [$("d-lido")]);
  normal.hidden = false;
}

// ---------- notificações ----------

function dispensado() {
  try {
    return localStorage.getItem(CHAVE_DISPENSADO) === "1";
  } catch {
    return false;
  }
}

function dispensar() {
  try {
    localStorage.setItem(CHAVE_DISPENSADO, "1");
  } catch {
    /* sem armazenamento: a tela pode voltar na próxima abertura */
  }
}

function deveOferecerNotificacoes() {
  return "PushManager" in window && "Notification" in window
    && Notification.permission === "default" && !dispensado();
}

function sairDasNotificacoes() {
  estado.notificacoes = false;
  if (location.hash !== "#/" && idDaRota() === null) location.hash = "#/";
  desenhar();
}

async function ativarNotificacoes() {
  const botao = $("ativar");
  botao.disabled = true;
  try {
    const permissao = await Notification.requestPermission();
    if (permissao === "granted") {
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      await navigator.serviceWorker.ready;
      const r = await fetch("/api/push/chave-publica");
      if (!r.ok) throw new Error("sem chave");
      const { chave } = await r.json();
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: base64urlParaBytes(chave),
      });
      const { endpoint, keys } = sub.toJSON();
      const env = await fetch("/api/push/inscrever", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint, keys }),
      });
      if (!env.ok) throw new Error("inscrição recusada");
    }
  } catch {
    /* falhou: segue para a lista sem derrubar nada */
  }
  botao.disabled = false;
  sairDasNotificacoes();
}

async function registrarServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  } catch {
    /* sem service worker o app continua funcionando */
  }
}

// ---------- início ----------

function iniciar() {
  $("atualizar").addEventListener("click", carregar);
  $("ativar").addEventListener("click", ativarNotificacoes);
  $("agora-nao").addEventListener("click", (e) => {
    e.preventDefault();
    dispensar();
    sairDasNotificacoes();
  });
  PC.addEventListener("change", desenhar);
  window.addEventListener("hashchange", () => {
    estado.notificacoes = false;
    desenhar();
    window.scrollTo(0, 0);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") carregar();
  });
  setInterval(() => {
    if (document.visibilityState === "visible") carregar();
  }, ATUALIZAR_A_CADA_MS);

  estado.notificacoes = deveOferecerNotificacoes();
  desenhar();
  carregar();
  registrarServiceWorker();
}

iniciar();
