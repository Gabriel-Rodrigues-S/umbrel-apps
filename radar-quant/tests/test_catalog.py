"""Testes do catálogo e da composição dos índices (sem acesso à internet)."""
import asyncio
import base64
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app import catalog, db
from app.config import Settings

FIX = Path(__file__).parent / "fixtures"


def fx(name):
    return (FIX / name).read_text()


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "radar.db")


def settings(tmp_path, provider="live"):
    return Settings(data_dir=tmp_path, provider=provider, refresh_hours=6)


def wikitext(n, fmt="plain"):
    rows = []
    for i in range(n):
        t = "".join(chr(65 + (i // d) % 26) for d in (676, 26, 1))  # AAA, AAB, ...
        first = "{{NasdaqSymbol|%s}}" % t if fmt == "tpl" else t
        rows.append(f"|-\n| {first} || [[Empresa {i}]] || Technology || Software")
    body = "{| class=\"wikitable\"\n! Ticker !! Company !! Industry !! Sub\n" + "\n".join(rows) + "\n|}"
    return json.dumps({"parse": {"title": "x", "wikitext": {"*": "Texto\n" + body}}})


def tickers(n):
    return [f"{chr(65 + i // 26)}{chr(65 + i % 26)}X" for i in range(n)]


def b3codes(n):
    return [f"{chr(65 + i // 26)}{chr(65 + i % 26)}CD3" for i in range(n)]


def b3idx(n):
    return json.dumps({"page": {}, "results": [{"cod": c, "asset": c} for c in b3codes(n)]})


def sp_csv(n):
    return "Symbol,Security\nBRK.B,Berkshire\n" + "\n".join(f"{t},Co" for t in tickers(n - 1)) + "\n"


# ---------- fetch_us ----------
def us_handler(req):
    if req.url.path.endswith("nasdaqlisted.txt"):
        return httpx.Response(200, text=fx("catalog_nasdaqlisted.txt"))
    return httpx.Response(200, text=fx("catalog_otherlisted.txt"))


def test_fetch_us_filtra_e_limpa_nomes():
    rows = run(catalog.fetch_us(httpx.MockTransport(us_handler)))
    assert rows == [("AAPL", "Apple Inc.", "Ação"),
                    ("AAAP", "Pacer Barings CLO Market Flex ETF", "ETF"),
                    ("MSFT", "Microsoft Corporation", "Ação"),
                    ("A", "Agilent Technologies, Inc.", "Ação"),
                    ("BRK.B", "Berkshire Hathaway Inc.", "Ação"),
                    ("SPY", "SPDR S&P 500 ETF Trust", "ETF")]


def test_fetch_us_http_500_e_corpo_grande():
    with pytest.raises(catalog.CatalogError):
        run(catalog.fetch_us(httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(catalog.CatalogError):
        run(catalog.fetch_us(httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 6_000_000))))


def test_fetch_us_sem_cabecalho_esperado():
    with pytest.raises(catalog.CatalogError):
        run(catalog.fetch_us(httpx.MockTransport(lambda r: httpx.Response(200, text="<html>oi</html>"))))


# ---------- fetch_b3 ----------
def test_fetch_b3_tipos_e_fracionarios():
    t = httpx.MockTransport(lambda r: httpx.Response(200, text=fx("catalog_brapi.json")))
    rows = run(catalog.fetch_b3(t))
    assert rows == [("PETR4", "PETROBRAS PN", "Ação"), ("VALE3", "VALE ON", "Ação"),
                    ("HGLG11", "CSHG LOGISTICA FII", "FII"),
                    ("BOVA11", "ISHARES IBOVESPA FUNDO DE INDICE", "ETF"),
                    ("XFIX11", "FUNDO XPTO", "ETF"), ("AAPL34", "APPLE DRN", "BDR")]


def test_fetch_b3_json_invalido():
    for resp in (httpx.Response(200, text="não é json"), httpx.Response(200, json={"stocks": "x"}),
                 httpx.Response(503)):
        with pytest.raises(catalog.CatalogError):
            run(catalog.fetch_b3(httpx.MockTransport(lambda r, resp=resp: resp)))


# ---------- fetch_index ----------
def test_fetch_index_b3_usa_base64_e_cod():
    seen = []

    def h(req):
        seen.append(req.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, text=b3idx(80))

    got = run(catalog.fetch_index("IBRA", httpx.MockTransport(h)))
    assert got == b3codes(80)
    sent = json.loads(base64.b64decode(seen[0]))
    assert sent["index"] == "IBRA" and sent["pageSize"] == 300 and sent["language"] == "pt-br"


def test_fetch_index_sp500_mantem_ponto():
    t = httpx.MockTransport(lambda r: httpx.Response(200, text=sp_csv(450)))
    got = run(catalog.fetch_index("SP500", t))
    assert got[0] == "BRK.B" and len(got) == 450


@pytest.mark.parametrize("index,n,body", [("IBOV", 39, b3idx), ("IBRA", 79, b3idx), ("SP500", 399, sp_csv)])
def test_fetch_index_abaixo_do_piso(index, n, body):
    t = httpx.MockTransport(lambda r: httpx.Response(200, text=body(n)))
    with pytest.raises(catalog.CatalogError):
        run(catalog.fetch_index(index, t))


@pytest.mark.parametrize("fmt", ["plain", "tpl"])
def test_fetch_index_ndx_wikitext(fmt):
    t = httpx.MockTransport(lambda r: httpx.Response(200, text=wikitext(100, fmt)))
    got = run(catalog.fetch_index("NDX", t))
    assert len(got) == 100 and got[0] == "AAA" and got[1] == "AAB"


@pytest.mark.parametrize("n", [50, 120])
def test_fetch_index_ndx_fora_da_faixa(n):
    t = httpx.MockTransport(lambda r: httpx.Response(200, text=wikitext(n)))
    with pytest.raises(catalog.CatalogError):
        run(catalog.fetch_index("NDX", t))


def test_fetch_index_ndx_fallback_de_pagina():
    pages = []

    def h(req):
        pages.append(req.url.params["page"])
        if len(pages) == 1:
            return httpx.Response(404)
        return httpx.Response(200, text=wikitext(100))

    assert len(run(catalog.fetch_index("NDX", httpx.MockTransport(h)))) == 100
    assert pages == ["List_of_NASDAQ-100_companies", "Nasdaq-100"]
    pages.clear()

    def few(req):
        pages.append(req.url.params["page"])
        return httpx.Response(200, text=wikitext(100 if len(pages) == 2 else 5))

    assert len(run(catalog.fetch_index("NDX", httpx.MockTransport(few)))) == 100


def test_fetch_index_ndx_wikitext_nao_string():
    body = json.dumps({"parse": {"wikitext": {"*": 5}}})
    with pytest.raises(catalog.CatalogError):
        run(catalog.fetch_index("NDX", httpx.MockTransport(lambda r: httpx.Response(200, text=body))))


def test_corpo_grande_em_b3_e_indices():
    big = httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 6_000_000))
    with pytest.raises(catalog.CatalogError):
        run(catalog.fetch_b3(big))
    for idx in ("IBOV", "SP500", "NDX"):
        with pytest.raises(catalog.CatalogError):
            run(catalog.fetch_index(idx, big))


def test_nomes_limitados_em_b3_e_eua():
    long = "  Nome\x00 com   espaços " + "x" * 500
    b3 = {"stocks": [{"stock": "PETR4", "name": long, "type": "stock"}]}
    rows = run(catalog.fetch_b3(httpx.MockTransport(lambda r: httpx.Response(200, json=b3))))
    assert len(rows[0][1]) == 80 and rows[0][1].startswith("Nome com espaços x")
    us = "Symbol|Security Name|Test Issue|ETF\nAAA|" + long + "|N|N\n"
    rows = run(catalog.fetch_us(httpx.MockTransport(
        lambda r: httpx.Response(200, text=us if "nasdaq" in r.url.path else
                                 "ACT Symbol|Security Name|Test Issue|ETF\nBBB|Outra|N|N\n"))))
    assert len(rows[0][1]) == 80 and "\x00" not in rows[0][1]


def test_fetch_us_exige_colunas_e_linhas_nos_dois_arquivos():
    ok_other = "ACT Symbol|Security Name|Test Issue|ETF\nBBB|Outra|N|N\n"
    ok_nasdaq = "Symbol|Security Name|Test Issue|ETF\nAAA|Uma|N|N\n"
    cases = [("Symbol|Security Name|Test Issue\nAAA|Uma|N\n", ok_other),  # sem ETF
             (ok_nasdaq, "ACT Symbol|Security Name|Test Issue|ETF\n"),     # otherlisted sem linhas
             ("Symbol|Security Name|Test Issue|ETF\n", ok_other)]
    for nas, oth in cases:
        t = httpx.MockTransport(lambda r, nas=nas, oth=oth: httpx.Response(
            200, text=nas if "nasdaq" in r.url.path else oth))
        with pytest.raises(catalog.CatalogError):
            run(catalog.fetch_us(t))


def test_fetch_index_erros():
    with pytest.raises(ValueError):
        run(catalog.fetch_index("FOO"))
    for resp in (httpx.Response(500), httpx.Response(200, text="lixo"),
                 httpx.Response(200, json={"results": []})):
        with pytest.raises(catalog.CatalogError):
            run(catalog.fetch_index("IBOV", httpx.MockTransport(lambda r, resp=resp: resp)))


# ---------- sintético, stale ----------
def test_crypto_catalog():
    assert len(catalog.CRYPTO_CATALOG) == 20
    assert [c[0] for c in catalog.CRYPTO_CATALOG[:2]] == ["BTC", "ETH"]
    assert all(c[2] == "Cripto" for c in catalog.CRYPTO_CATALOG)


def test_synthetic_catalog():
    markets, idx = catalog.synthetic_catalog()
    assert ("BOVA11", "iShares Ibovespa", "ETF") in markets["B3"]
    assert ("IJKL11", "Gama FII", "FII") in markets["B3"]
    assert ("BRK.B", "Berkshire Hathaway", "Ação") in markets["US"]
    assert markets["CRYPTO"] == catalog.CRYPTO_CATALOG
    assert idx["IBOV"] == ["PETR4", "VALE3", "ITUB4", "BBAS3", "WEGE3"]
    assert idx["IBRA"] == idx["IBOV"] + ["ABCD3", "EFGH4", "MNOP3"]
    assert idx["NDX"] == ["AAPL", "MSFT", "NVDA", "TSLA"] and len(idx["SP500"]) == 8


def test_refresh_sintetico_grava_tudo(conn, tmp_path):
    assert catalog.catalog_is_stale(conn)
    out = run(catalog.refresh_catalog(conn, settings(tmp_path, "synthetic")))
    assert out["errors"] == [] and out["markets"]["B3"] == 10 and out["indices"]["IBRA"] == 8
    assert db.catalog_count(conn, "US") == 11
    assert [m["symbol"] for m in db.index_members(conn, "NDX")] == ["AAPL", "MSFT", "NVDA", "TSLA"]
    assert not catalog.catalog_is_stale(conn)


def test_catalog_is_stale_por_idade(conn, tmp_path):
    run(catalog.refresh_catalog(conn, settings(tmp_path, "synthetic")))
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    db.set_meta(conn, "catalog_refreshed_at", old)
    assert catalog.catalog_is_stale(conn)
    db.set_meta(conn, "catalog_refreshed_at", "lixo")
    assert catalog.catalog_is_stale(conn)


# ---------- Review Focus 2: falhas independentes ----------
def test_refresh_live_preserva_o_que_falhou(conn, tmp_path):
    db.replace_catalog_market(conn, "US", [("OLD", "Velho", "Ação")])
    db.set_index_members(conn, "IBRA", "B3", ["AACD3"])
    b3 = {}
    b3["stocks"] = [{"stock": f"{chr(65 + i // 26)}{chr(65 + i % 26)}CD3", "name": f"E{i}", "type": "stock"}
                    for i in range(250)]
    nasdaq = "Symbol|Security Name|Test Issue|ETF\n" + "\n".join(f"US{i}|Co {i}|N|N" for i in range(10))

    def h(req):
        u = str(req.url)
        if "nasdaqlisted" in u:
            return httpx.Response(200, text=nasdaq)
        if "otherlisted" in u:
            return httpx.Response(200, text="ACT Symbol|Security Name|Test Issue|ETF\n")
        if "brapi" in u:
            return httpx.Response(200, json=b3)
        if "b3.com.br" in u:
            if json.loads(base64.b64decode(u.rsplit("/", 1)[-1]))["index"] == "IBRA":
                return httpx.Response(500)
            return httpx.Response(200, text=b3idx(76))
        if "constituents" in u:
            return httpx.Response(200, text=sp_csv(503))
        return httpx.Response(200, text=wikitext(100))

    out = run(catalog.refresh_catalog(conn, settings(tmp_path), httpx.MockTransport(h)))
    assert len(out["errors"]) == 2
    assert out["markets"]["B3"] == 250 and "US" not in out["markets"]
    assert db.catalog_entry(conn, "OLD", "US") is not None and db.catalog_entry(conn, "US0", "US") is None
    assert [m["symbol"] for m in db.index_members(conn, "IBRA")] == ["AACD3"]
    assert [m["symbol"] for m in db.index_members(conn, "IBOV")] == sorted(b3codes(76))
    assert len(db.index_members(conn, "NDX")) == 100
    assert len(db.index_members(conn, "SP500")) == 503
    assert db.catalog_count(conn, "CRYPTO") == 20
    # falha parcial: sem carimbo de 7 dias; nova tentativa só 6 h depois (não a cada ciclo do laço)
    assert db.get_meta(conn, "catalog_refreshed_at") is None
    attempt = datetime.fromisoformat(db.get_meta(conn, "catalog_attempt_at"))
    assert not catalog.catalog_is_stale(conn)
    db.set_meta(conn, "catalog_attempt_at", (attempt - timedelta(hours=5, minutes=50)).isoformat())
    assert not catalog.catalog_is_stale(conn)
    db.set_meta(conn, "catalog_attempt_at", (attempt - timedelta(hours=6, minutes=1)).isoformat())
    assert catalog.catalog_is_stale(conn)


def test_refresh_live_tudo_fora_do_ar_nao_marca_atualizado(conn, tmp_path):
    db.replace_catalog_market(conn, "B3", [("PETR4", "Petrobras", "Ação")])
    out = run(catalog.refresh_catalog(conn, settings(tmp_path),
                                      httpx.MockTransport(lambda r: httpx.Response(500))))
    assert len(out["errors"]) == 6 and out["markets"] == {"CRYPTO": 20}
    assert db.catalog_entry(conn, "PETR4", "B3") is not None
    assert db.get_meta(conn, "catalog_refreshed_at") is None and db.get_meta(conn, "catalog_attempt_at")


def test_refresh_nao_substitui_indice_que_encolheu_a_menos_da_metade(conn, tmp_path):
    db.set_index_members(conn, "IBOV", "B3", b3codes(100))

    def h(req):
        if "b3.com.br" in str(req.url):
            return httpx.Response(200, text=b3idx(45))  # acima do piso (40), abaixo de 50
        return httpx.Response(500)

    out = run(catalog.refresh_catalog(conn, settings(tmp_path), httpx.MockTransport(h)))
    assert len(db.index_members(conn, "IBOV")) == 100
    assert any(e.startswith("IBOV") for e in out["errors"]) and "IBOV" not in out["indices"]
    # 60 (>= metade) é aceito
    h2 = lambda req: httpx.Response(200, text=b3idx(60)) if "b3.com.br" in str(req.url) else httpx.Response(500)
    run(catalog.refresh_catalog(conn, settings(tmp_path), httpx.MockTransport(h2)))
    assert len(db.index_members(conn, "IBOV")) == 60


def test_falha_parcial_depois_de_carimbo_valido_e_sucesso_seguinte(conn, tmp_path):
    run(catalog.refresh_catalog(conn, settings(tmp_path, "synthetic")))
    assert db.get_meta(conn, "catalog_attempt_at") is None and not catalog.catalog_is_stale(conn)
    stamp = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()  # completa há 2 dias
    db.set_meta(conn, "catalog_refreshed_at", stamp)
    out = run(catalog.refresh_catalog(conn, settings(tmp_path), httpx.MockTransport(lambda r: httpx.Response(500))))
    assert out["errors"] and db.get_meta(conn, "catalog_refreshed_at") == stamp  # carimbo antigo intacto
    old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    db.set_meta(conn, "catalog_attempt_at", old)
    assert catalog.catalog_is_stale(conn)  # tentativa com falha há mais de 6 h
    db.set_meta(conn, "catalog_attempt_at", "lixo")
    assert not catalog.catalog_is_stale(conn)  # tentativa ilegível: vale o carimbo
    db.set_meta(conn, "catalog_attempt_at", old)
    run(catalog.refresh_catalog(conn, settings(tmp_path, "synthetic")))  # sucesso completo
    assert not catalog.catalog_is_stale(conn)
