"""Testes do nome completo aprendido (sem acesso à internet)."""
import asyncio

import httpx
import pytest

from app import db, names, search

NAMES = {"BBAS3.SA": "Banco do Brasil S.A.", "PETR4.SA": "Petróleo Brasileiro S.A. - Petrobras",
         "VALE3.SA": "Vale S.A.", "ITUB4.SA": "Itaú Unibanco Holding S.A.", "BRK-B": "Berkshire Hathaway Inc."}


def run(coro):
    return asyncio.run(coro)


def transport(calls=None, down=()):
    """Yahoo de mentira: devolve o papel pedido e um vizinho; `down` = tickers que derrubam a rede."""
    def handler(request):
        q = request.url.params["q"]
        if calls is not None:
            calls.append(q)
        if q in down or "*" in down:
            raise httpx.ConnectError("fora do ar", request=request)
        quotes = [{"symbol": q + "X", "exchange": "SAO", "longname": "Vizinho errado"}]
        if q in NAMES:
            quotes.append({"symbol": q, "exchange": "SAO", "longname": f"  {NAMES[q]}\n"})
        return httpx.Response(200, json={"quotes": quotes})
    return httpx.MockTransport(handler)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "radar.db")
    db.replace_catalog_market(c, "B3", [(s, s, "Ação") for s in ("BBAS3", "PETR4", "VALE3", "ITUB4", "ZZZZ3")])
    search.invalidate()
    names._unnamed.clear()
    return c


class Sleep:
    def __init__(self):
        self.calls = []

    async def __call__(self, seconds):
        self.calls.append(seconds)


# ---------- fetch_name ----------

def test_fetch_name():
    calls = []
    t = transport(calls)
    assert run(names.fetch_name("BBAS3", "B3", t)) == "Banco do Brasil S.A."
    assert run(names.fetch_name("BRK.B", "US", t)) == "Berkshire Hathaway Inc."
    assert run(names.fetch_name("ZZZZ3", "B3", t)) is None  # só o vizinho: não é o ticker exato
    assert run(names.fetch_name("BTC", "CRYPTO", t)) is None
    assert calls == ["BBAS3.SA", "BRK-B", "ZZZZ3.SA"]


def test_fetch_name_usa_shortname_e_saneia():
    quotes = [{"symbol": "BOVA11.SA", "shortname": "ISHARES  BOVA\tCI\x00"}, {"symbol": "HGLG11.SA", "longname": " "}]
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"quotes": quotes}))
    assert run(names.fetch_name("BOVA11", "B3", t)) == "ISHARES BOVA CI"
    assert run(names.fetch_name("HGLG11", "B3", t)) is None


def test_fetch_name_falhas_devolvem_none():
    def timeout(request):
        raise httpx.ReadTimeout("lento", request=request)

    for t in (transport(down=("*",)), httpx.MockTransport(timeout),
              httpx.MockTransport(lambda r: httpx.Response(500)),
              httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>")),
              httpx.MockTransport(lambda r: httpx.Response(200, content=b" " * 2_000_000))):
        assert run(names.fetch_name("BBAS3", "B3", t)) is None


# ---------- learn_names ----------

def test_learn_names_grava_e_nao_toca_quem_ja_tem(conn):
    db.set_alias(conn, "PETR4", "B3", "Já aprendido")
    calls, sleep = [], Sleep()
    assert search.search_local(conn, "banco do brasil") == []
    n = run(names.learn_names(conn, "B3", ["BBAS3", "PETR4", "VALE3", "FORA3"], pace=0.5, sleep=sleep,
                              transport=transport(calls)))
    assert n == 2 and calls == ["BBAS3.SA", "VALE3.SA"]  # PETR4 já tinha; FORA3 não está no catálogo
    assert sleep.calls == [0.5]  # entre chamadas, não depois da última
    assert db.catalog_entry(conn, "BBAS3", "B3")["name"] == "Banco do Brasil S.A."
    assert db.catalog_entry(conn, "PETR4", "B3")["name"] == "Já aprendido"
    assert [r["symbol"] for r in search.search_local(conn, "banco do brasil")] == ["BBAS3"]  # índice derrubado


def test_learn_names_limite(conn):
    calls = []
    todos = ["BBAS3", "PETR4", "VALE3", "ITUB4"]
    assert run(names.learn_names(conn, "B3", todos, pace=0, limit=3, sleep=Sleep(), transport=transport(calls))) == 3
    assert calls == ["BBAS3.SA", "PETR4.SA", "VALE3.SA"]
    assert run(names.learn_names(conn, "B3", todos, pace=0, limit=3, sleep=Sleep(), transport=transport(calls))) == 1
    assert db.missing_alias(conn, "B3", todos) == []
    assert run(names.learn_names(conn, "B3", todos, pace=0, sleep=Sleep(), transport=transport(calls))) == 0
    assert len(calls) == 4


def test_learn_names_para_em_tres_falhas_seguidas(conn):
    calls = []
    todos = ["BBAS3", "PETR4", "VALE3", "ITUB4"]
    t = transport(calls, down=("PETR4.SA", "VALE3.SA", "ITUB4.SA"))
    assert run(names.learn_names(conn, "B3", todos + ["ZZZZ3"], pace=0, sleep=Sleep(), transport=t)) == 1
    assert calls == ["BBAS3.SA", "PETR4.SA", "VALE3.SA", "ITUB4.SA"]  # ZZZZ3 nem foi tentado
    calls.clear()  # falha isolada não interrompe: o contador zera a cada resposta da fonte
    t = transport(calls, down=("PETR4.SA", "ITUB4.SA"))
    assert run(names.learn_names(conn, "B3", todos, pace=0, sleep=Sleep(), transport=t)) == 1
    assert calls == ["PETR4.SA", "VALE3.SA", "ITUB4.SA"]


def test_learn_names_sem_nome_na_fonte_nao_trava_a_fila(conn):
    """Papel que a fonte não conhece não conta como falha de rede nem é tentado de novo neste processo."""
    calls = []
    t, lote = transport(calls), ["ZZZZ3", "BBAS3"]
    assert run(names.learn_names(conn, "B3", lote, pace=0, sleep=Sleep(), transport=t)) == 1
    assert run(names.learn_names(conn, "B3", lote, pace=0, sleep=Sleep(), transport=t)) == 0
    assert calls == ["ZZZZ3.SA", "BBAS3.SA"]
    assert db.missing_alias(conn, "B3", ["ZZZZ3"]) == ["ZZZZ3"]


# ---------- rodada final ----------

def test_learn_names_falha_ao_gravar_pula_o_papel_e_segue(conn, monkeypatch):
    real, calls = db.set_alias, []

    def set_alias(c, symbol, market, alias):
        if symbol == "BBAS3":
            raise UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed")
        return real(c, symbol, market, alias)

    monkeypatch.setattr(db, "set_alias", set_alias)
    t, lote = transport(calls), ["BBAS3", "PETR4", "VALE3"]
    assert run(names.learn_names(conn, "B3", lote, pace=0, sleep=Sleep(), transport=t)) == 2
    assert calls == ["BBAS3.SA", "PETR4.SA", "VALE3.SA"] and db.missing_alias(conn, "B3", lote) == ["BBAS3"]
    assert run(names.learn_names(conn, "B3", lote, pace=0, sleep=Sleep(), transport=t)) == 0
    assert len(calls) == 3  # o papel que não grava não é tentado de novo neste processo


def test_learn_names_saneia_substituto_e_deixa_o_nome_legivel(conn):
    import json
    nomes = {"BBAS3.SA": "BCO\ud800 BRASIL S.A.", "PETR4.SA": "PETROLEO BRASILEIRO S.A. PETROBRAS"}

    def handler(request):
        q = request.url.params["q"]
        body = json.dumps({"quotes": [{"symbol": q, "longname": nomes[q]}]})
        return httpx.Response(200, content=body.encode())

    n = run(names.learn_names(conn, "B3", ["BBAS3", "PETR4"], pace=0, sleep=Sleep(),
                              transport=httpx.MockTransport(handler)))
    assert n == 2
    assert {c["symbol"]: c["alias"] for c in db.all_catalog(conn) if c["alias"]} == {
        "BBAS3": "BCO Brasil S.A.", "PETR4": "Petroleo Brasileiro S.A. Petrobras"}
