"""Interface estática: páginas, Chart.js local e ausência de CDN."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def test_raiz_serve_comparacao(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Comparar" in r.text


def test_paginas(cliente):
    for caminho in ("/sessao", "/dados"):
        r = cliente.get(caminho)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


def test_chartjs_local(cliente):
    assert cliente.get("/static/vendor/chart.umd.min.js").status_code == 200


def test_sem_cdn():
    for nome in ("index.html", "sessao.html", "dados.html"):
        html = (STATIC / nome).read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)\s*=\s*["']https?://""", html), nome
        assert not re.search(r"""(src|href)\s*=\s*["']/""", html), nome


def test_docs_continua(cliente):
    assert cliente.get("/docs").status_code == 200
