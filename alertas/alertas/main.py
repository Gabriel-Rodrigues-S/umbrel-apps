"""Rotas do app de alertas (porta 8445).

- POST /api/alertas: remetentes com token próprio (Bearer).
- GET /saude: sem identidade, não revela nada.
- Todo o resto: só o Gabriel (cabeçalho do Tailscale vindo do host), senão 403.
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Literal

import anyio
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import banco, push
from .identidade import gateway_do_conteiner, usuario_confiavel
from .remetentes import Remetentes

log = logging.getLogger("alertas")

ESTATICOS = Path(__file__).resolve().parent / "static"
SEM_CACHE = {"Cache-Control": "no-cache"}


class EstaticosSemCache(StaticFiles):
    """Arquivos de /static sempre revalidados (ETag), para uma atualização da imagem pegar na hora."""

    def file_response(self, *args, **kwargs):
        r = super().file_response(*args, **kwargs)
        r.headers["Cache-Control"] = "no-cache"
        return r

ROTAS_PUBLICAS = {("POST", "/api/alertas"), ("GET", "/saude")}
LIMITE_CORPO = 64 * 1024
JANELA_DESCONHECIDO = 600  # no máximo 1 alerta de remetente desconhecido a cada 10 min
INTERVALO_LIMPEZA = 86400
RETENCAO_DIAS = 365


class NovoAlerta(BaseModel):
    model_config = ConfigDict(extra="ignore")  # "origem" no corpo é ignorada
    gravidade: Literal["grave", "normal", "info"]
    titulo: StrictStr = Field(min_length=1, max_length=120)
    detalhes: StrictStr = Field(default="", max_length=20000)


class Chaves(BaseModel):
    model_config = ConfigDict(extra="ignore")
    p256dh: StrictStr = Field(min_length=1, max_length=200)
    auth: StrictStr = Field(min_length=1, max_length=100)


class Inscricao(BaseModel):
    model_config = ConfigDict(extra="ignore")
    endpoint: StrictStr = Field(max_length=2048)
    keys: Chaves

    @field_validator("endpoint")
    @classmethod
    def _https(cls, v: str) -> str:
        from urllib.parse import urlsplit
        try:
            p = urlsplit(v)
        except ValueError:
            raise ValueError("endpoint inválido") from None
        if p.scheme != "https" or not p.hostname:
            raise ValueError("endpoint inválido")
        return v


def ler_config(dados: Path) -> dict:
    """config/app.json; qualquer problema = {} (falha fechada: sem usuário, sem host)."""
    try:
        d = json.loads((dados / "config" / "app.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _erro(status: int, msg: str, **kw) -> JSONResponse:
    return JSONResponse({"erro": msg}, status_code=status, **kw)


def criar_app(dados: Path, *, ip_host: str | None = None, usuario_permitido: str | None = None,
              enviar_push=None) -> FastAPI:
    dados = Path(dados)
    if ip_host is None:
        ip_host = gateway_do_conteiner()
    if not ip_host:
        log.warning("gateway do contêiner desconhecido: interface fechada (403)")
    db = dados / "alertas.db"
    remetentes = Remetentes(dados / "config" / "remetentes.json")

    def usuario() -> str | None:
        if usuario_permitido is not None:
            return usuario_permitido
        u = ler_config(dados).get("usuario_permitido")
        return u if isinstance(u, str) and u else None

    def com_banco(fn, *args, **kw):
        # uma conexão por operação (WAL aguenta leitores e um escritor; sem estado compartilhado)
        con = banco.abrir(db)
        try:
            return fn(con, *args, **kw)
        finally:
            con.close()

    def push_padrao(gravidade: str) -> None:
        try:
            k = push.chaves(dados / "config")
        except ValueError:
            log.warning("push não enviado: vapid.json malformado")
            return
        com_banco(push.enviar_todos, gravidade, k, host=ler_config(dados).get("host"))

    enviar = enviar_push or push_padrao

    def enviar_seguro(gravidade: str) -> None:
        try:
            enviar(gravidade)
        except Exception as e:
            log.warning("push falhou (%s)", type(e).__name__)

    async def limpeza_diaria():
        while True:
            try:
                n = await anyio.to_thread.run_sync(partial(com_banco, banco.limpar_antigos, RETENCAO_DIAS))
                if n:
                    log.info("retenção: %d alertas antigos apagados", n)
            except Exception as e:
                log.warning("limpeza falhou (%s)", type(e).__name__)
            await asyncio.sleep(INTERVALO_LIMPEZA)

    @asynccontextmanager
    async def ciclo(app):
        # cria o banco e liga o WAL antes de qualquer pedido ou da limpeza
        await anyio.to_thread.run_sync(partial(com_banco, lambda con: None))
        tarefa = asyncio.create_task(limpeza_diaria())
        try:
            yield
        finally:
            tarefa.cancel()

    app = FastAPI(lifespan=ciclo, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def identidade(request: Request, chamar):
        if (request.method, request.url.path) not in ROTAS_PUBLICAS:
            ip = request.client.host if request.client else None
            if not usuario_confiavel(ip, request.headers, usuario(), ip_host):
                return _erro(403, "proibido")
        return await chamar(request)

    @app.exception_handler(RequestValidationError)
    async def _validacao(request, exc):
        return _erro(422, "corpo inválido")  # sem ecoar o que veio

    @app.exception_handler(StarletteHTTPException)
    async def _http(request, exc):
        return _erro(exc.status_code, "não encontrado" if exc.status_code == 404 else "erro")

    @app.exception_handler(Exception)
    async def _interno(request, exc):
        log.error("erro interno (%s)", type(exc).__name__)
        return _erro(500, "erro interno")

    @app.get("/saude")
    async def saude():
        return {"ok": True}

    @app.post("/api/alertas", status_code=201)
    async def receber(request: Request, tarefas: BackgroundTasks):
        cab = request.headers.get("authorization", "")
        esquema, _, token = cab.partition(" ")
        nome = remetentes.remetente_do(token.strip()) if esquema.lower() == "bearer" else None
        if nome is None:
            ip = request.client.host if request.client else "desconhecido"
            detalhes = f"Um remetente desconhecido tentou enviar um alerta (IP de origem {ip})."
            novo = await anyio.to_thread.run_sync(partial(
                com_banco, banco.inserir_se_ausente, "alertas", "normal", "Remetente desconhecido",
                detalhes, janela_s=JANELA_DESCONHECIDO))
            if novo is not None:
                tarefas.add_task(enviar_seguro, "normal")
            return _erro(401, "não autorizado", headers={"WWW-Authenticate": "Bearer"},
                         background=tarefas)
        corpo = bytearray()
        async for parte in request.stream():
            corpo += parte
            if len(corpo) > LIMITE_CORPO:
                return _erro(413, "corpo grande demais")
        try:
            a = NovoAlerta.model_validate_json(bytes(corpo))
        except ValidationError:
            return _erro(422, "corpo inválido")
        i = await anyio.to_thread.run_sync(partial(
            com_banco, banco.inserir, nome, a.gravidade, a.titulo, a.detalhes))
        if push.texto(a.gravidade) is not None:
            tarefas.add_task(enviar_seguro, a.gravidade)
        return JSONResponse({"id": i}, status_code=201, background=tarefas)

    @app.get("/api/alertas")
    def listar():
        return com_banco(banco.listar)

    @app.post("/api/alertas/{id_}/lido")
    def lido(id_: int):
        if not com_banco(banco.marcar_lido, id_):
            return _erro(404, "não encontrado")
        return Response(status_code=204)

    @app.get("/api/push/chave-publica")
    def chave_publica():
        try:
            return {"chave": push.chaves(dados / "config")["publica"]}
        except ValueError:
            return _erro(503, "chaves de push indisponíveis")

    @app.post("/api/push/inscrever", status_code=201)
    def inscrever(sub: Inscricao):
        com_banco(banco.salvar_inscricao, sub.model_dump())
        return {"ok": True}

    # Interface (PWA). Tudo passa pelo middleware de identidade, inclusive /static, sw.js e manifest.
    @app.get("/")
    def raiz():
        return FileResponse(ESTATICOS / "index.html", media_type="text/html; charset=utf-8", headers=SEM_CACHE)

    @app.get("/sw.js")
    def service_worker():
        # na raiz, para o escopo do service worker cobrir "/"
        return FileResponse(ESTATICOS / "sw.js", media_type="text/javascript; charset=utf-8",
                            headers={**SEM_CACHE, "Service-Worker-Allowed": "/"})

    @app.get("/manifest.webmanifest")
    def manifesto():
        return FileResponse(ESTATICOS / "manifest.webmanifest", media_type="application/manifest+json",
                            headers=SEM_CACHE)

    app.mount("/static", EstaticosSemCache(directory=ESTATICOS), name="static")

    return app


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
app = criar_app(Path(os.environ.get("DADOS_DIR", "/app/data")))
