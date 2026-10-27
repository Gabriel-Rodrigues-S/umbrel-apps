"""Interface estática (PWA): manifest, service worker, index e exigência de identidade."""
import re
from pathlib import Path

import pytest

from test_api import api, app, dados, gabriel, push_falso  # noqa: F401  (fixtures reutilizadas)

pytestmark = pytest.mark.anyio

STATIC = Path(__file__).resolve().parent.parent / "alertas" / "static"


def ler(rel):
    return (STATIC.parent / rel).read_text(encoding="utf-8")


async def manifest(c):
    r = await c.get("/manifest.webmanifest")
    assert r.status_code == 200
    return r.json()


# --- testes do brief ---

async def test_manifest_standalone(gabriel):
    assert (await manifest(gabriel))["display"] == "standalone"


def test_sw_nao_monta_texto_proprio():
    assert "event.data.text()" in ler("static/sw.js")


async def test_index_exige_identidade(api):
    assert (await api.get("/")).status_code == 403


# --- extras ---

CAMINHOS = ["/", "/sw.js", "/manifest.webmanifest", "/static/app.js", "/static/estilo.css",
            "/static/formato.js", "/static/icone-192.png", "/static/icone-512.png", "/static/icone-apple-180.png",
            "/static/fontes/IBMPlexSans-var.woff2"]


@pytest.mark.parametrize("caminho", CAMINHOS)
async def test_estaticos_exigem_identidade(api, caminho):
    assert (await api.get(caminho)).status_code == 403


@pytest.mark.parametrize("caminho", CAMINHOS)
async def test_estaticos_com_identidade(gabriel, caminho):
    r = await gabriel.get(caminho)
    assert r.status_code == 200
    assert len(r.content) > 0


async def test_tipos_de_conteudo(gabriel):
    assert "text/html" in (await gabriel.get("/")).headers["content-type"]
    assert "javascript" in (await gabriel.get("/sw.js")).headers["content-type"]
    assert "manifest+json" in (await gabriel.get("/manifest.webmanifest")).headers["content-type"]


async def test_cache_revalida(gabriel):
    for caminho in ("/static/app.js", "/static/estilo.css", "/sw.js", "/"):
        assert "no-cache" in (await gabriel.get(caminho)).headers.get("cache-control", ""), caminho


async def test_sw_no_escopo_raiz(gabriel):
    r = await gabriel.get("/sw.js")
    assert r.headers.get("service-worker-allowed", "/") == "/"
    assert "no-cache" in r.headers.get("cache-control", "")


async def test_manifest_campos(gabriel):
    m = await manifest(gabriel)
    assert m["name"] == "Alertas" and m["start_url"] == "/"
    assert m["theme_color"] == "#F4F5F7" and m["background_color"] == "#F4F5F7"
    assert {i["sizes"] for i in m["icons"]} == {"192x192", "512x512"}
    for i in m["icons"]:
        r = await gabriel.get(i["src"])
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"


def test_sw_sem_innerhtml_e_so_texto_do_push():
    sw = ler("static/sw.js")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", sw)
    assert sw.count("event.data.text()") == 1
    assert "event.data.json" not in sw
    assert "caches." not in sw  # sem cache offline de dados da API


def test_app_js_sem_innerhtml():
    for nome in ("static/app.js", "static/formato.js"):
        js = ler(nome)
        assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function", js), nome


def test_sem_host_externo():
    for nome in ("static/index.html", "static/estilo.css", "static/app.js", "static/formato.js",
                 "static/sw.js", "static/manifest.webmanifest"):
        assert "https://" not in ler(nome).replace("http://www.w3.org/2000/svg", ""), nome
        assert not re.search(r"//fonts\.|googleapis|gstatic", ler(nome)), nome


def test_fontes_locais_com_licenca():
    d = STATIC / "fontes"
    # Plex Sans é uma fonte variável (um arquivo cobre 400, 500 e 600)
    for nome in ("IBMPlexSans-var", "IBMPlexMono-400", "IBMPlexMono-500"):
        assert (d / f"{nome}.woff2").read_bytes()[:4] == b"wOF2"
    assert "SIL Open Font License" in (d / "OFL.txt").read_text(encoding="utf-8")


def test_index_com_um_unico_main():
    assert ler("static/index.html").count("<main") == 1
