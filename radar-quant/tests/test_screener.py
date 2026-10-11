import asyncio
import json
from datetime import datetime, timezone

import pytest

from app import analysis, catalog, db, screener, service, universe
from app.config import Settings
from app.stats.swing import SETUPS


def run(coro):
    return asyncio.run(coro)


def make_settings(tmp_path):
    return Settings(data_dir=tmp_path, provider="synthetic", refresh_hours=6)


def new_conn(tmp_path):
    conn = db.connect(tmp_path / "radar.db")
    run(catalog.refresh_catalog(conn, make_settings(tmp_path)))
    return conn


@pytest.fixture
def conn(tmp_path):
    return new_conn(tmp_path)


@pytest.fixture(scope="module")
def uni(tmp_path_factory):
    """Universo sintético já atualizado (somente leitura): linhas gravadas para todos os membros."""
    d = tmp_path_factory.mktemp("scr")
    c = new_conn(d)
    out = run(universe.refresh_universe(c, make_settings(d), pace=0, sleep=_nosleep))
    assert not out["aborted"]
    return c


async def _nosleep(_):
    return None


def add(conn, symbol, market="B3", watch=True, refresh=False, tmp_path=None):
    aid = db.add_asset(conn, symbol, market, watch=watch)
    if refresh:
        run(service.refresh_asset(conn, db.get_asset(conn, aid), Settings(
            data_dir=tmp_path, provider="synthetic", refresh_hours=6)))
    return db.get_asset(conn, aid)


def fake_row(a, **kw):
    base = {"id": a["id"], "symbol": a["symbol"], "market": a["market"], "name": a["symbol"], "price": 10.0,
            "change_pct": 0.01, "score": 10.0, "verdict": "manter", "evidence": "sem_evidencia",
            "momentum": 0.1, "trend": 0.1, "dist_sma200": 0.1, "reversal": 0.1, "volatility": 0.2,
            "drawdown": -0.1, "above_sma200": True,
            "setups": {k: {"state": "nenhum", "evidence": "amostra_insuficiente"} for k in SETUPS},
            "as_of": "2026-10-07", "pool": {k: [[202001, 0.01]] for k in SETUPS}}
    base.update(kw)
    db.upsert_screener(db_conn_of(a), a["id"], base["as_of"], base)
    return base


_CONN = {}


def db_conn_of(a):
    return _CONN["c"]


def put(conn, a, **kw):
    _CONN["c"] = conn
    return fake_row(a, **kw)


# ---------- build_row / store_row ----------

def test_build_row_campos(uni):
    a = db.find_asset(uni, "PETR4", "B3")
    row = screener.build_row(uni, a)
    for k in ("id", "symbol", "market", "name", "price", "change_pct", "score", "verdict", "evidence",
              "momentum", "trend", "dist_sma200", "reversal", "volatility", "drawdown", "above_sma200",
              "setups", "as_of", "pool"):
        assert k in row
    assert row["name"] == "Petrobras PN" and row["id"] == a["id"]
    assert set(row["pool"]) == set(SETUPS) and set(row["setups"]) == set(SETUPS)
    assert all({"state", "evidence"} == set(v) for v in row["setups"].values())
    df = service.load_frame(uni, a["id"])
    assert row["price"] == pytest.approx(df["close"].iloc[-1])
    assert row["change_pct"] == pytest.approx(df["close"].iloc[-1] / df["close"].iloc[-2] - 1)
    raw = {f["key"]: f for f in analysis.analyze_asset(uni, a)["factors"]}
    assert row["above_sma200"] is (raw["dist_sma200"]["raw"] > 0)
    assert row["momentum"] == pytest.approx(raw["momentum"]["normalized"])
    json.dumps(row, allow_nan=False)


def test_build_row_insuficiente(tmp_path, conn):
    a = add(conn, "CURTO1", refresh=True, tmp_path=tmp_path)
    assert screener.build_row(conn, a) is None


def test_store_row_grava_e_apaga_linha_insuficiente(tmp_path, conn):
    ok = add(conn, "PETR4", refresh=True, tmp_path=tmp_path)
    curto = add(conn, "CURTO1", refresh=True, tmp_path=tmp_path)
    assert screener.store_row(conn, ok) is True
    assert screener.progress(conn, "watchlist")["ready"] == 1
    put(conn, curto)  # linha antiga que a análise atual já não sustenta
    assert screener.progress(conn, "watchlist")["ready"] == 2
    assert screener.store_row(conn, curto) is False
    assert screener.progress(conn, "watchlist") == {"scope": "watchlist", "total": 2, "ready": 2,
                                                    "insufficient": 1, "failed": 0}
    assert [r["symbol"] for r in screener.query(conn)["rows"]] == ["PETR4"]


# ---------- scope_assets / progress ----------

def test_scope_assets(uni):
    assert {a["symbol"] for a in screener.scope_assets(uni, "NDX")} == {"AAPL", "MSFT", "NVDA", "TSLA"}
    assert len(screener.scope_assets(uni, "IBRA")) == 8
    assert screener.scope_assets(uni, "watchlist") == []
    with pytest.raises(screener.ScreenerError):
        screener.scope_assets(uni, "XYZ")


def test_progress(tmp_path, conn):
    universe.ensure_assets(conn)
    assert screener.progress(conn, "IBOV") == {"scope": "IBOV", "total": 5, "ready": 0, "insufficient": 0, "failed": 0}
    for sym in ("PETR4", "VALE3"):
        a = add_existing(conn, sym, tmp_path)
        assert screener.store_row(conn, a)
    assert screener.progress(conn, "IBOV")["ready"] == 2
    assert screener.progress(conn, "SP500")["ready"] == 0


def test_progress_conta_insuficiente_e_falha_como_processados(tmp_path, conn):
    universe.ensure_assets(conn)
    ids = {a["symbol"]: a for a in screener.scope_assets(conn, "IBOV")}
    assert screener.store_row(conn, add_existing(conn, "PETR4", tmp_path))  # linha válida
    db.upsert_screener(conn, ids["VALE3"]["id"], "", {"status": "insuficiente"})  # menos de 300 candles
    db.set_refresh_status(conn, ids["ITUB4"]["id"], "símbolo não encontrado")  # falha na fonte, sem linha
    assert screener.progress(conn, "IBOV") == {"scope": "IBOV", "total": 5, "ready": 3, "insufficient": 1, "failed": 1}
    # falha num ativo que já tem linha válida: segue pronto, não conta como falha
    db.set_refresh_status(conn, ids["PETR4"]["id"], "fonte fora")
    # falha num ativo com marcador: processado uma vez só
    db.set_refresh_status(conn, ids["VALE3"]["id"], "fonte fora")
    assert screener.progress(conn, "IBOV") == {"scope": "IBOV", "total": 5, "ready": 3, "insufficient": 1, "failed": 2}
    for sym in ("BBAS3", "WEGE3"):
        assert screener.store_row(conn, add_existing(conn, sym, tmp_path))
    p = screener.progress(conn, "IBOV")
    assert p["ready"] == p["total"] == 5  # a montagem termina


def add_existing(conn, symbol, tmp_path):
    a = db.find_asset(conn, symbol, "B3")
    run(service.refresh_asset(conn, a, make_settings(tmp_path)))
    return db.get_asset(conn, a["id"])


# ---------- query ----------

def test_query_watchlist_calcula_o_que_falta(tmp_path, conn):
    add(conn, "PETR4", refresh=True, tmp_path=tmp_path)
    add(conn, "VALE3", refresh=True, tmp_path=tmp_path)
    add(conn, "CURTO1", refresh=True, tmp_path=tmp_path)
    add(conn, "ABCD3", refresh=False)  # nunca atualizado: não calcula
    add(conn, "EFGH4", watch=False, refresh=True, tmp_path=tmp_path)  # fora da watchlist
    out = screener.query(conn)
    assert out["scope"] == "watchlist" and out["page"] == 1 and out["page_size"] == 50
    assert {r["symbol"] for r in out["rows"]} == {"PETR4", "VALE3"} and out["total"] == 2
    assert out["updated_at"] is not None
    assert len(db.load_screener(conn)) == 3  # 2 válidas + marcador do ativo curto


def test_query_indice_so_membros_gravados(uni):
    out = screener.query(uni, scope="SP500")
    assert out["total"] == 8 and {r["market"] for r in out["rows"]} == {"US"}
    assert all("pool" not in r for r in out["rows"])
    assert screener.query(uni, scope="watchlist")["total"] == 0
    assert screener.query(uni, scope="watchlist")["updated_at"] is None


def test_query_indice_nao_calcula_na_hora(tmp_path, conn):
    universe.ensure_assets(conn)
    add_existing(conn, "PETR4", tmp_path)
    assert screener.query(conn, scope="IBOV")["total"] == 0


def test_query_filtros(uni):
    allrows = screener.query(uni, scope="IBRA", page_size=200)["rows"]
    assert screener.query(uni, scope="IBRA", market="US")["total"] == 0
    assert screener.query(uni, scope="SP500", market="US")["total"] == 8
    for v in ("comprar", "manter", "vender"):
        got = screener.query(uni, scope="SP500", verdict=v, page_size=200)["rows"]
        want = [r for r in screener.query(uni, scope="SP500", page_size=200)["rows"] if r["verdict"] == v]
        assert {r["id"] for r in got} == {r["id"] for r in want}
    for e in ("favoravel", "contraria", "sem_evidencia"):
        got = screener.query(uni, scope="IBRA", evidence=e, page_size=200)["rows"]
        assert {r["id"] for r in got} == {r["id"] for r in allrows if r["evidence"] == e}
    for key in SETUPS:
        got = screener.query(uni, scope="IBRA", setup=key, page_size=200)["rows"]
        want = {r["id"] for r in allrows if r["setups"][key]["state"] in ("sinal", "posicao")}
        assert {r["id"] for r in got} == want


def test_query_filtro_setup_e_ordenacao_sinteticos(conn):
    a, b, c = (add(conn, s) for s in ("AAA1", "BBB1", "CCC1"))
    sig = {"reversao": {"state": "sinal", "evidence": "favoravel"},
           **{k: {"state": "nenhum", "evidence": "amostra_insuficiente"} for k in SETUPS if k != "reversao"}}
    pos = {**sig, "reversao": {"state": "posicao", "evidence": "favoravel"}}
    put(conn, a, setups=sig, volatility=0.30, score=5.0)
    put(conn, b, setups=pos, volatility=None, score=50.0)
    put(conn, c, volatility=0.10, score=-20.0)
    assert {r["symbol"] for r in screener.query(conn, setup="reversao")["rows"]} == {"AAA1", "BBB1"}
    by = lambda **kw: [r["symbol"] for r in screener.query(conn, **kw)["rows"]]  # noqa: E731
    assert by() == ["BBB1", "AAA1", "CCC1"]  # score desc
    assert by(sort="symbol", order="asc") == ["AAA1", "BBB1", "CCC1"]
    assert by(sort="symbol", order="desc") == ["CCC1", "BBB1", "AAA1"]
    assert by(sort="volatility", order="desc") == ["AAA1", "CCC1", "BBB1"]
    assert by(sort="volatility", order="asc") == ["CCC1", "AAA1", "BBB1"]  # None sempre por último


def test_query_paginacao(uni):
    p1 = screener.query(uni, scope="IBRA", page_size=3, sort="symbol", order="asc")
    p2 = screener.query(uni, scope="IBRA", page_size=3, page=2, sort="symbol", order="asc")
    p4 = screener.query(uni, scope="IBRA", page_size=3, page=4)
    assert p1["total"] == p2["total"] == 8 and len(p1["rows"]) == len(p2["rows"]) == 3
    assert p2["page"] == 2 and p4["rows"] == [] and p4["total"] == 8
    syms = [r["symbol"] for r in p1["rows"] + p2["rows"]]
    assert syms == sorted(syms) and len(set(syms)) == 6


@pytest.mark.parametrize("kw", [
    {"scope": "XYZ"}, {"market": "MARS"}, {"verdict": "talvez"}, {"evidence": "x"}, {"setup": "nada"},
    {"sort": "inexistente"}, {"order": "up"}, {"page": 0}, {"page_size": 0}, {"page_size": 500}])
def test_query_parametros_invalidos(uni, kw):
    with pytest.raises(screener.ScreenerError):
        screener.query(uni, **kw)


# ---------- summary ----------

def test_summary(uni):
    rows = screener.query(uni, scope="IBRA", page_size=200)["rows"]
    s = screener.summary(uni, "IBRA")
    assert s["scope"] == "IBRA" and s["count"] == len(rows) == 8
    assert s["pct_above_sma200"] == pytest.approx(sum(r["above_sma200"] for r in rows) / 8)
    assert s["verdicts"] == {v: sum(r["verdict"] == v for r in rows) for v in ("comprar", "manter", "vender")}
    assert [x["key"] for x in s["setups"]] == list(SETUPS)
    for x in s["setups"]:
        assert x["label"] == SETUPS[x["key"]]["label"]
        assert x["active"] == sum(r["setups"][x["key"]]["state"] in ("sinal", "posicao") for r in rows)
        assert set(x["pooled"]) >= {"trades", "win_rate", "mean_excess", "ci_low", "ci_high", "evidence"}
    json.dumps(s, allow_nan=False)


def test_summary_vazio(uni):
    s = screener.summary(uni, "watchlist")
    assert s["count"] == 0 and s["pct_above_sma200"] is None
    assert all(x["pooled"]["evidence"] == "amostra_insuficiente" and x["active"] == 0 for x in s["setups"])


def test_summary_cache(uni, monkeypatch):
    calls = []
    real = screener.pooled_evidence
    monkeypatch.setattr(screener, "pooled_evidence", lambda pool: calls.append(1) or real(pool))
    first = screener.summary(uni, "NDX")
    n = len(calls)
    assert n > 0
    first["count"] = 999  # mexer na cópia não corrompe o cache
    again = screener.summary(uni, "NDX")
    assert len(calls) == n and again["count"] == 4 and again is not first
    a = db.find_asset(uni, "AAPL", "US")
    assert screener.store_row(uni, a)  # linha regravada: muda o updated_at, invalida o cache
    screener.summary(uni, "NDX")
    assert len(calls) > n


def test_summary_escopo_invalido(uni):
    with pytest.raises(screener.ScreenerError):
        screener.summary(uni, "XYZ")


def test_linha_antiga_sem_setups_e_above_nulo(conn):
    a, b = add(conn, "AAA1"), add(conn, "BBB1")
    put(conn, a, setups={}, above_sma200=None)
    put(conn, b, above_sma200=True)
    assert [r["symbol"] for r in screener.query(conn, setup="reversao")["rows"]] == []
    s = screener.summary(conn, "watchlist")
    assert s["count"] == 2 and s["pct_above_sma200"] == 1.0
    assert all(x["active"] == 0 for x in s["setups"])


def test_pct_acima_todas_nulas(conn):
    put(conn, add(conn, "AAA1"), above_sma200=None)
    s = screener.summary(conn, "watchlist")
    assert s["count"] == 1 and s["pct_above_sma200"] is None


def test_build_row_above_nulo_quando_bruto_nulo(uni, monkeypatch):
    a = db.find_asset(uni, "PETR4", "B3")
    real = analysis.analyze_asset

    def fake(c, asset):
        out = dict(real(c, asset))
        out["factors"] = [{**f, "raw": None} if f["key"] == "dist_sma200" else f for f in out["factors"]]
        return out
    monkeypatch.setattr(analysis, "analyze_asset", fake)
    assert screener.build_row(uni, a)["above_sma200"] is None


# ---------- revisão final: nome, pregão em andamento e linhas atrasadas ----------

def test_query_preenche_nome_nulo_pelo_catalogo(conn):
    universe.ensure_assets(conn)
    a, b = db.find_asset(conn, "PETR4", "B3"), db.find_asset(conn, "VALE3", "B3")
    put(conn, a, name=None, score=2.0)  # gravada antes de o catálogo chegar
    put(conn, b, name=None, score=1.0)
    assert [r["name"] for r in screener.query(conn, scope="IBOV")["rows"]] == ["Petrobras PN", "Vale ON"]
    assert db.load_screener(conn, [a["id"]])[0]["payload"]["name"] is None  # só a resposta é completada
    seen = []
    real = db.catalog_entry
    try:
        db.catalog_entry = lambda c, s, m: seen.append(s) or real(c, s, m)
        rows = screener.query(conn, scope="IBOV", page_size=1)["rows"]
    finally:
        db.catalog_entry = real
    assert [r["name"] for r in rows] == ["Petrobras PN"] and seen == ["PETR4"]  # só as linhas da página
    fora = add(conn, "ZZZZ3")  # fora do catálogo: segue nulo
    put(conn, fora, name=None)
    assert screener.query(conn)["rows"][0]["name"] is None


def test_query_session_open(conn, monkeypatch):
    b3, us, btc = add(conn, "PETR4"), add(conn, "AAPL", "US"), add(conn, "BTC", "CRYPTO")
    for a in (b3, us, btc):
        put(conn, a)
    assert [r["session_open"] for r in screener.query(conn)["rows"]] == [False] * 3
    monkeypatch.setattr(analysis, "_now", lambda: datetime(2026, 10, 7, 15, tzinfo=timezone.utc))  # dia do `as_of`
    got = {r["symbol"]: r["session_open"] for r in screener.query(conn)["rows"]}
    assert got == {"PETR4": True, "AAPL": True, "BTC": False}
    monkeypatch.setattr(analysis, "_now", lambda: datetime(2026, 10, 7, 21, 30, tzinfo=timezone.utc))
    assert [r["session_open"] for r in screener.query(conn)["rows"]] == [False] * 3  # depois do fechamento
    assert "session_open" not in db.load_screener(conn, [b3["id"]])[0]["payload"]  # calculado na consulta


def test_query_stale_rows(conn):
    a, b, c = (add(conn, s) for s in ("AAA1", "BBB1", "CCC1"))
    for x in (a, b, c):
        put(conn, x)
    assert screener.query(conn)["stale_rows"] == 0
    put(conn, a, as_of="2026-10-06")
    put(conn, b, as_of="2026-10-02")
    assert screener.query(conn)["stale_rows"] == 2
    assert screener.query(conn, verdict="comprar")["stale_rows"] == 2  # do escopo, não do filtro
    assert screener.query(conn, page_size=1)["stale_rows"] == 2
    # cripto negocia todo dia: o candle mais novo dela não torna atrasadas as ações
    put(conn, add(conn, "BTC", "CRYPTO"), as_of="2026-10-08")
    assert screener.query(conn)["stale_rows"] == 2


def test_query_devolve_o_nome_atual_do_catalogo(conn):
    """1.1.1: linha gravada com o nome antigo mostra o nome exibido de agora (alias aprendido depois)."""
    universe.ensure_assets(conn)
    a = db.find_asset(conn, "BBAS3", "B3")
    put(conn, a, name="BCO BRASIL S.A.")
    assert screener.query(conn, scope="IBOV")["rows"][0]["name"] == "Banco do Brasil ON"
    db.set_alias(conn, "BBAS3", "B3", "Banco do Brasil S.A.")
    assert screener.query(conn, scope="IBOV")["rows"][0]["name"] == "Banco do Brasil S.A."
    assert db.load_screener(conn, [a["id"]])[0]["payload"]["name"] == "BCO BRASIL S.A."  # só a resposta muda
    fora = add(conn, "ZZZZ3")  # fora do catálogo: fica o nome gravado
    put(conn, fora, name="Nome gravado")
    assert screener.query(conn)["rows"][0]["name"] == "Nome gravado"
