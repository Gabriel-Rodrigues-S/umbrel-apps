"""Servidor do gateway: autenticação por cliente + MCP (streamable HTTP) + status."""
import asyncio
import contextvars
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import auditoria, ferramentas
from .avisos import Avisos, avisos_de_config
from .caminhos import Negado
from .rajada import Rajada
from .tokens import Tokens

NOMES = ("listar", "ler", "buscar", "recentes")
INTERVALO_REENVIO_S = 60
HORA_RESUMO = 8
MAX_ALVO_LOG = 300
MAX_ALVO_AVISO = 200
MAX_FERRAMENTA = 64

# cliente autenticado da requisição atual (copiado para as tarefas do MCP)
_cliente: contextvars.ContextVar[str | None] = contextvars.ContextVar("cliente", default=None)

PAGINA = ("<!doctype html><meta charset=\"utf-8\"><title>Gateway do vault</title>"
          "<p>Gateway do vault — ativo</p>")


def _erro_stderr(msg: str) -> None:
    print(f"vault-gateway: {msg}", file=sys.stderr, flush=True)


def _limpo(valor: Any, limite: int) -> str:
    """str, sem surrogates (não quebram JSON/UTF-8) e truncado."""
    s = valor if isinstance(valor, str) else str(valor)
    return s[:limite].encode("utf-8", "replace").decode("utf-8")


def _json(dado: Any) -> str:
    # nomes de arquivo com bytes inválidos viram '?'
    return json.dumps(dado, ensure_ascii=False, indent=1).encode("utf-8", "replace").decode("utf-8")


def _erro(msg: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=msg)], isError=True)


class _ErroNeutro(Exception):
    """Erro de ferramenta com mensagem segura para o cliente."""


def proximas_8h(agora: datetime) -> datetime:
    """Próximo 08:00 estritamente depois de `agora` (mesmo fuso de `agora`)."""
    alvo = agora.replace(hour=HORA_RESUMO, minute=0, second=0, microsecond=0)
    if alvo <= agora:
        alvo = (alvo + timedelta(days=1)).replace(hour=HORA_RESUMO)
    return alvo


def resumo_diario(rajada: Rajada, enviar: Callable[[str, str, str], None]) -> None:
    total = rajada.total_do_dia()
    rajada.zerar_dia()
    enviar("info", "Resumo diário",
           f"Tentativas com token ausente ou inválido nas últimas 24 h: {total}")


class _Despachante:
    """Fila primeiro: grava o aviso no disco já na chamada; uma única thread drena (posta e apaga).

    A rede nunca roda no event loop nem no caminho da requisição.
    """

    def __init__(self, avisos):
        self.avisos = avisos
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="avisos")
        self._trava = threading.Lock()
        self._drenagem_pendente = False

    def _drenar(self):
        with self._trava:
            self._drenagem_pendente = False
        try:
            return self.avisos.reenviar_fila()
        except Exception:
            _erro_stderr("falha ao reenviar avisos")
            return None

    def _agendar(self):
        """No máximo uma drenagem na espera (rajadas não empilham tentativas de rede)."""
        with self._trava:
            if self._drenagem_pendente:
                return None
            self._drenagem_pendente = True
        try:
            return self._exec.submit(self._drenar)
        except RuntimeError:
            with self._trava:
                self._drenagem_pendente = False
            return None

    def enviar(self, gravidade: str, titulo: str, detalhes: str) -> None:
        """Escrita local rápida (chamar fora do event loop); a rede fica com a thread."""
        try:
            self.avisos.guardar(gravidade, titulo, detalhes)
        except Exception:
            _erro_stderr("falha ao gravar aviso na fila")
        self._agendar()

    async def reenviar(self) -> None:
        fut = self._agendar()
        if fut is not None:
            await asyncio.wrap_future(fut)

    def esperar(self, timeout: float = 30) -> None:
        """Bloqueia até tudo o que foi enfileirado antes terminar (para testes)."""
        self._exec.submit(lambda: None).result(timeout)

    def encerrar(self) -> None:
        self._exec.shutdown(wait=True)


class _Autenticacao:
    """Middleware ASGI puro: exige Authorization: Bearer <token> válido."""

    def __init__(self, app, *, tokens: Tokens, rajada: Rajada, registrar, despachante: _Despachante):
        self.app = app
        self.tokens = tokens
        self.rajada = rajada
        self.registrar = registrar
        self.despachante = despachante

    @staticmethod
    def _credencial(scope) -> tuple[str | None, str | None]:
        """(token, motivo de falha)."""
        valores = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
        if not valores:
            return None, "token_ausente"
        valor = valores[0].decode("latin-1").strip()
        if not valor:
            return None, "token_ausente"
        if len(valores) > 1:
            return None, "token_invalido"
        esquema, _, cred = valor.partition(" ")
        cred = cred.strip()
        if esquema.lower() != "bearer" or not cred or any(c.isspace() for c in cred):
            return None, "token_invalido"
        return cred, None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token, motivo = self._credencial(scope)
        nome = None
        if token is not None:
            try:
                nome = self.tokens.cliente_do(token)
            except Exception:
                _erro_stderr("erro ao validar token")
            if nome is None:
                motivo = "token_invalido"
        del token  # nunca registrado
        if nome is None:
            await self._negar(scope, receive, send, motivo)
            return
        marca = _cliente.set(nome)
        try:
            await self.app(scope, receive, send)
        finally:
            _cliente.reset(marca)

    async def _negar(self, scope, receive, send, motivo):
        await anyio.to_thread.run_sync(lambda: self.registrar(
            cliente=None, ferramenta=_limpo(scope.get("method", "-"), MAX_FERRAMENTA),
            alvo=_limpo(scope.get("path", ""), MAX_ALVO_LOG), resultado="negada", motivo=motivo))
        if self.rajada.contar(time.time()):
            n = self.rajada.na_janela()
            minutos = round(self.rajada.janela_s / 60)
            await anyio.to_thread.run_sync(
                self.despachante.enviar, "normal", "Rajada de tokens inválidos",
                f"{n} tentativas com token ausente ou inválido nos últimos {minutos} minutos")
        resp = JSONResponse({"erro": "não autorizado"}, status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
        await resp(scope, receive, send)


class _MCPGateway(FastMCP):
    """FastMCP que trata ferramenta desconhecida e nunca devolve detalhes internos."""

    def __init__(self, *args, negar_desconhecida, **kwargs):
        super().__init__(*args, **kwargs)
        self._negar_desconhecida = negar_desconhecida

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        cliente = _cliente.get()
        if cliente is None:  # falha fechada: sem identidade, nada roda
            _erro_stderr("chamada de ferramenta sem cliente autenticado")
            return _erro("Erro interno.")
        if name not in NOMES:
            await anyio.to_thread.run_sync(self._negar_desconhecida, cliente, name)
            return _erro("Ferramenta desconhecida.")
        try:
            return await super().call_tool(name, arguments)
        except ToolError as e:
            causa = e.__cause__
            if isinstance(causa, _ErroNeutro):
                return _erro(str(causa))
            if isinstance(causa, ValidationError):
                return _erro("Argumentos inválidos.")
            _erro_stderr(f"erro inesperado na ferramenta {name}: {type(causa or e).__name__}")
            return _erro("Erro interno.")
        except Exception as e:
            _erro_stderr(f"erro inesperado na ferramenta {name}: {type(e).__name__}")
            return _erro("Erro interno.")


def criar_app(raiz: Path, dados: Path, *, tokens: Tokens | None = None, avisos=None) -> Starlette:
    raiz, dados = Path(raiz), Path(dados)
    tokens = tokens or Tokens(dados / "config/tokens.json")
    avisos = avisos if avisos is not None else avisos_de_config(dados)
    log = dados / "logs/acesso.jsonl"
    rajada = Rajada()
    despachante = _Despachante(avisos)
    trava_log = threading.Lock()

    def registrar(**campos) -> None:
        """Erro de disco no log nunca vira erro da requisição."""
        try:
            with trava_log:
                auditoria.registrar(log, **campos)
        except Exception:
            _erro_stderr("falha ao gravar o log de acesso")

    def avisar_negada(cliente: str, ferramenta: str, alvo: str, motivo: str) -> None:
        despachante.enviar(
            "grave", f"Tentativa negada: cliente {cliente}",
            f"ferramenta: {ferramenta}\nalvo: {_limpo(alvo, MAX_ALVO_AVISO)}\nmotivo: {motivo}")

    def negar_desconhecida(cliente: str, nome: Any) -> None:
        nome = _limpo(nome, MAX_FERRAMENTA)
        registrar(cliente=cliente, ferramenta=nome, alvo="", resultado="negada",
                  motivo="ferramenta_desconhecida")
        avisar_negada(cliente, nome, "", "ferramenta_desconhecida")

    def executar(ferramenta: str, alvo: str, fn: Callable[[], Any]) -> str:
        """Roda numa thread: chama a ferramenta, registra e traduz erros para mensagens neutras."""
        cliente = _cliente.get()
        alvo = _limpo(alvo, MAX_ALVO_LOG)
        try:
            resultado = fn()
        except Negado as e:
            registrar(cliente=cliente, ferramenta=ferramenta, alvo=alvo,
                      resultado="negada", motivo=e.motivo)
            avisar_negada(cliente, ferramenta, alvo, e.motivo)
            raise _ErroNeutro("Acesso negado.") from None
        except ferramentas.NaoEncontrado:
            registrar(cliente=cliente, ferramenta=ferramenta, alvo=alvo,
                      resultado="permitida", motivo=None)
            raise _ErroNeutro("Não encontrado.") from None
        except ferramentas.NaoLegivel:
            registrar(cliente=cliente, ferramenta=ferramenta, alvo=alvo,
                      resultado="permitida", motivo=None)
            raise _ErroNeutro("Arquivo não pode ser lido.") from None
        except Exception as e:
            _erro_stderr(f"erro inesperado em {ferramenta}: {type(e).__name__}")
            raise _ErroNeutro("Erro interno.") from None
        registrar(cliente=cliente, ferramenta=ferramenta, alvo=alvo,
                  resultado="permitida", motivo=None)
        return resultado if isinstance(resultado, str) else _json(resultado)

    async def rodar(ferramenta: str, alvo: str, fn: Callable[[], Any]) -> str:
        # E/S do vault fora do event loop (contextvars seguem para a thread)
        return await anyio.to_thread.run_sync(executar, ferramenta, alvo, fn)

    mcp = _MCPGateway(
        "vault-gateway",
        instructions="Acesso somente de leitura a um vault Obsidian.",
        stateless_http=True,
        json_response=True,
        log_level="WARNING",
        negar_desconhecida=negar_desconhecida,
        # proteção de DNS rebinding desligada: o acesso exige token e o Host vem do Funnel
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool(name="listar", description="Lista arquivos e pastas de uma pasta do vault ('' = raiz).",
              structured_output=False)
    async def listar(pasta: str = "") -> str:
        return await rodar("listar", pasta, lambda: ferramentas.listar(raiz, pasta))

    @mcp.tool(name="ler", description="Lê o conteúdo de um arquivo de texto do vault.",
              structured_output=False)
    async def ler(caminho: str) -> str:
        return await rodar("ler", caminho, lambda: ferramentas.ler(raiz, caminho))

    @mcp.tool(name="buscar", description="Busca um texto nas notas (até 50 resultados).",
              structured_output=False)
    async def buscar(texto: str, limite: int = 50) -> str:
        limite = max(1, min(50, limite))
        return await rodar("buscar", texto, lambda: ferramentas.buscar(raiz, texto, limite))

    @mcp.tool(name="recentes", description="Arquivos modificados mais recentemente (até 100).",
              structured_output=False)
    async def recentes(n: int = 20) -> str:
        n = max(1, min(100, n))
        return await rodar("recentes", str(n), lambda: ferramentas.recentes(raiz, n))

    mcp.streamable_http_app()  # cria o session manager
    app_mcp = _Autenticacao(StreamableHTTPASGIApp(mcp.session_manager), tokens=tokens,
                            rajada=rajada, registrar=registrar, despachante=despachante)

    async def laco_reenvio():
        while True:
            await despachante.reenviar()
            await asyncio.sleep(INTERVALO_REENVIO_S)

    async def laco_resumo():
        while True:
            alvo = proximas_8h(datetime.now().astimezone())
            # dorme em pedaços: robusto a ajuste de relógio e suspensão
            while (falta := (alvo - datetime.now().astimezone()).total_seconds()) > 0:
                await asyncio.sleep(min(falta, 300))
            await anyio.to_thread.run_sync(resumo_diario, rajada, despachante.enviar)

    @asynccontextmanager
    async def ciclo(_app):
        async with mcp.session_manager.run():
            tarefas = [asyncio.create_task(laco_reenvio()), asyncio.create_task(laco_resumo())]
            try:
                yield
            finally:
                for t in tarefas:
                    t.cancel()
                await asyncio.gather(*tarefas, return_exceptions=True)
                await anyio.to_thread.run_sync(despachante.encerrar)

    async def saude(_request):
        return JSONResponse({"ok": True})

    async def inicio(_request):
        return HTMLResponse(PAGINA)

    app = Starlette(
        routes=[
            Route("/saude", saude, methods=["GET"]),
            Route("/", inicio, methods=["GET"]),
            # as duas formas, sem redirecionamento (que perderia o Authorization)
            Route("/mcp", app_mcp),
            Route("/mcp/", app_mcp),
        ],
        lifespan=ciclo,
    )
    app.state.avisos = avisos
    app.state.esperar_avisos = despachante.esperar
    return app


def _app_do_ambiente() -> Starlette:
    return criar_app(Path(os.environ.get("VAULT_DIR", "/data/vault")),
                     Path(os.environ.get("DADOS_DIR", "/data")))


_app = None


def __getattr__(nome: str):
    """`app` criado só quando o uvicorn pede (importar o módulo nos testes não lê /data)."""
    global _app
    if nome == "app":
        if _app is None:
            _app = _app_do_ambiente()
        return _app
    raise AttributeError(nome)
