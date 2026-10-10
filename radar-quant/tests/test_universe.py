import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app import analysis, catalog, db, screener, service, universe
from app.config import Settings
from app.providers.base import ProviderError, UnknownSymbol
from app.providers.synthetic import SyntheticProvider


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, provider="synthetic", refresh_hours=6, universe_pace=0.25)


@pytest.fixture
def conn(tmp_path, settings):
    c = db.connect(tmp_path / "radar.db")
    run(catalog.refresh_catalog(c, settings))
    analysis.invalidate()
    return c


class Sleeps:
    def __init__(self):
        self.calls = []

    async def __call__(self, s):
        self.calls.append(s)


class Flaky:
    """Provider sintético que falha para os símbolos pedidos."""

    def __init__(self, bad, exc=ProviderError("fonte fora")):
        self.bad, self.exc, self.inner = bad, exc, SyntheticProvider()

    async def fetch_daily(self, symbol, market):
        if self.bad is True or symbol in self.bad:
            raise self.exc
        return await self.inner.fetch_daily(symbol, market)


def index_ids(conn):
    return {a["symbol"]: a["id"] for a in db.list_assets(conn, watch=None)}


def n_members(conn):
    return len({(m["symbol"], m["market"]) for m in db.index_members(conn)})


# ---------- ensure_assets ----------

def test_ensure_assets_cria_e_e_idempotente(conn):
    assert db.list_assets(conn, watch=None) == []
    n = universe.ensure_assets(conn)
    assert n == n_members(conn) == 16  # IBRA (8 B3) + SP500 (8 US)
    assert all(a["watch"] == 0 for a in db.list_assets(conn, watch=None))
    assert universe.ensure_assets(conn) == 0
    assert len(db.list_assets(conn, watch=None)) == 16


def test_ensure_assets_preserva_watchlist(conn):
    aid = db.add_asset(conn, "PETR4", "B3", watch=True)
    assert universe.ensure_assets(conn) == 15
    assert db.get_asset(conn, aid)["watch"] == 1
    assert len([a for a in db.list_assets(conn, watch=None) if a["symbol"] == "PETR4"]) == 1


# ---------- refresh_universe ----------

def test_refresh_universe_completo(conn, settings):
    sl = Sleeps()
    out = run(universe.refresh_universe(conn, settings, sleep=sl))
    assert out == {"updated": 16, "skipped": 0, "failed": 0, "aborted": False}
    assert db.get_meta(conn, "universe_refreshed_at")
    assert sl.calls and set(sl.calls) == {0.25}
    assert len(sl.calls) == 15  # entre ativos, não antes do primeiro
    assert screener.progress(conn, "IBRA") == {"scope": "IBRA", "total": 8, "ready": 8, "insufficient": 0, "failed": 0}
    assert screener.progress(conn, "SP500")["ready"] == 8
    out2 = run(universe.refresh_universe(conn, settings, sleep=sl))
    assert out2 == {"updated": 0, "skipped": 16, "failed": 0, "aborted": False}


def test_refresh_universe_pace_explicito(conn, settings):
    sl = Sleeps()
    run(universe.refresh_universe(conn, settings, pace=0.0, limit=2, sleep=sl))
    assert sl.calls == [0.0]


def test_refresh_universe_limit_e_parcial(conn, settings):
    out = run(universe.refresh_universe(conn, settings, limit=2, sleep=Sleeps()))
    assert out == {"updated": 2, "skipped": 0, "failed": 0, "aborted": False}
    assert db.get_meta(conn, "universe_refreshed_at") is None
    out2 = run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    assert out2["updated"] == 14 and out2["skipped"] == 2
    assert db.get_meta(conn, "universe_refreshed_at")


def test_refresh_universe_pula_atualizados_e_reprocessa_velhos(conn, settings):
    run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()  # sempre anterior ao último corte
    a = db.find_asset(conn, "PETR4", "B3")
    conn.execute("UPDATE assets SET last_refresh = ? WHERE id = ?", (old, a["id"]))
    conn.commit()
    out = run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    assert out["updated"] == 1 and out["skipped"] == 15


def test_refresh_universe_aborta_apos_falhas_seguidas(conn, settings, monkeypatch):
    monkeypatch.setattr(service, "get_provider", lambda market, s: Flaky(True))
    sl = Sleeps()
    out = run(universe.refresh_universe(conn, settings, sleep=sl))
    assert out == {"updated": 0, "skipped": 0, "failed": universe.MAX_FAILS, "aborted": True}
    assert db.get_meta(conn, "universe_refreshed_at") is None
    assert len(sl.calls) == universe.MAX_FAILS - 1


def test_refresh_universe_simbolo_desconhecido_conta_falha_sem_apagar(conn, settings, monkeypatch):
    monkeypatch.setattr(service, "get_provider", lambda market, s: Flaky(True, UnknownSymbol("x")))
    out = run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    assert out["aborted"] and out["failed"] == universe.MAX_FAILS
    assert len(db.list_assets(conn, watch=None)) == 16


def test_refresh_universe_falhas_intercaladas_nao_abortam(conn, settings, monkeypatch):
    universe.ensure_assets(conn)
    order = [a["symbol"] for a in db.list_assets(conn, watch=None)]
    bad = set(order[1::2])  # uma sim, outra não
    monkeypatch.setattr(service, "get_provider", lambda market, s: Flaky(bad))
    out = run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    assert out == {"updated": 8, "skipped": 0, "failed": 8, "aborted": False}
    assert db.get_meta(conn, "universe_refreshed_at")


# ---------- universe_due ----------

def _t(h, m=0, day=9):
    return datetime(2026, 10, day, h, m, tzinfo=timezone.utc)


def test_cutoff_bordas():
    assert universe.cutoff(_t(4, 59)) == _t(5, day=8)
    assert universe.cutoff(_t(5, 0)) == _t(5)
    assert universe.cutoff(_t(23, 59)) == _t(5)
    assert universe.cutoff(datetime(2026, 10, 9, 4, 59)) == _t(5, day=8)  # sem fuso: tratado como UTC
    assert universe.cutoff is service.cutoff


def test_universe_due(conn):
    assert universe.universe_due(conn, _t(6)) is True  # nunca rodou
    assert universe.universe_due(conn, _t(14)) is True  # nunca rodou: a qualquer hora
    db.set_meta(conn, "universe_refreshed_at", _t(5, 30).isoformat())
    assert universe.universe_due(conn, _t(6)) is False  # já completou depois do corte de hoje
    db.set_meta(conn, "universe_refreshed_at", _t(4, 0).isoformat())
    assert universe.universe_due(conn, _t(6)) is True  # completa, mas anterior ao corte
    assert universe.universe_due(conn, _t(14)) is False  # fora da janela 05–09 UTC
    assert universe.universe_due(conn, _t(4, 30)) is False
    db.set_meta(conn, "universe_refreshed_at", "lixo")
    assert universe.universe_due(conn, _t(14)) is True


def test_universe_due_primeira_passada_durante_o_pregao(conn):
    db.set_meta(conn, "universe_attempt_at", _t(14, 25, day=8).isoformat())
    db.set_meta(conn, "universe_refreshed_at", _t(14, 40, day=8).isoformat())
    assert universe.universe_due(conn, _t(20, day=8)) is False
    assert universe.universe_due(conn, _t(4, 59)) is False
    assert universe.universe_due(conn, _t(6)) is True  # antes: 15 h 20 < 20 h e a janela do dia era pulada
    assert universe.universe_due(conn, _t(8, 59)) is True
    assert universe.universe_due(conn, _t(9)) is False
    db.set_meta(conn, "universe_attempt_at", _t(5, 5).isoformat())
    assert universe.universe_due(conn, _t(6)) is False  # tentativa há menos de RETRY_HOURS
    db.set_meta(conn, "universe_refreshed_at", _t(5, 20).isoformat())
    assert universe.universe_due(conn, _t(8)) is False
    assert universe.universe_due(conn, _t(6, day=10)) is True


def test_ativo_atualizado_no_pregao_fica_desatualizado_no_corte():
    a = {"last_refresh": _t(15, day=8).isoformat()}
    assert universe._stale(a, _t(23, day=8)) is False
    assert universe._stale(a, _t(4, 59)) is False
    assert universe._stale(a, _t(5, 30)) is True  # antes: 14 h 30 < 20 h e o candle parcial ficava
    assert universe._stale({"last_refresh": _t(5, 10).isoformat()}, _t(5, 30)) is False
    assert universe._stale({"last_refresh": None}, _t(5, 30)) is True
    assert universe._stale({"last_refresh": "lixo"}, _t(5, 30)) is True


# ---------- purge ----------

def test_purge(conn):
    universe.ensure_assets(conn)
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    old = (now - timedelta(days=31)).isoformat()
    recent = (now - timedelta(days=5)).isoformat()
    ids = {s: db.add_asset(conn, s, "B3", watch=w) for s, w in
           [("VELHO1", False), ("RECENTE1", False), ("WATCH1", True)]}
    member = db.find_asset(conn, "PETR4", "B3")["id"]
    for aid, ts in [(ids["VELHO1"], old), (ids["RECENTE1"], recent), (ids["WATCH1"], old), (member, old)]:
        conn.execute("UPDATE assets SET last_viewed = ? WHERE id = ?", (ts, aid))
    conn.commit()
    assert universe.purge(conn, now) == 1
    left = {a["symbol"] for a in db.list_assets(conn, watch=None)}
    assert "VELHO1" not in left and {"RECENTE1", "WATCH1", "PETR4"} <= left


def test_universe_due_espera_apos_aborto(conn, settings, monkeypatch):
    monkeypatch.setattr(service, "get_provider", lambda market, s: Flaky(True))
    out = run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    assert out["aborted"]
    assert db.get_meta(conn, "universe_attempt_at")
    now = datetime.now(timezone.utc)
    assert universe.universe_due(conn, now) is False
    assert universe.universe_due(conn, now + timedelta(hours=1, minutes=59)) is False
    assert universe.universe_due(conn, now + timedelta(hours=2, minutes=1)) is True  # nunca completou


def test_universe_due_depois_de_passada_completa(conn, settings):
    run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    now = datetime.now(timezone.utc)
    assert universe.universe_due(conn, now + timedelta(minutes=30)) is False
    t = (now + timedelta(days=2)).replace(hour=6, minute=0)
    assert universe.universe_due(conn, t) is True
    assert universe.universe_due(conn, t.replace(hour=14)) is False


def test_passada_solta_da_memoria_a_analise_de_quem_nao_e_watchlist(conn, settings):
    aid = db.add_asset(conn, "PETR4", "B3", watch=True)
    run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    assert len(db.load_screener(conn)) == 16
    assert set(analysis._cache) == {aid}  # os demais são recalculados sob demanda ao abrir
    other = db.find_asset(conn, "VALE3", "B3")
    assert analysis.analyze_asset(conn, other)["status"] == "ok"


def test_refresh_universe_falha_no_store_row_conta_falha_e_segue(conn, settings, monkeypatch):
    real = screener.store_row

    def boom(c, a):
        if a["symbol"] == "PETR4":
            raise RuntimeError("estourou")
        return real(c, a)
    monkeypatch.setattr(screener, "store_row", boom)
    out = run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    assert out == {"updated": 15, "skipped": 0, "failed": 1, "aborted": False}


def test_purge_async(conn):
    universe.ensure_assets(conn)
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    aid = db.add_asset(conn, "VELHO1", "B3", watch=False)
    conn.execute("UPDATE assets SET last_viewed = ? WHERE id = ?", ((now - timedelta(days=40)).isoformat(), aid))
    conn.commit()
    assert run(universe.purge_async(conn, now)) == 1


def test_catalogo_vazio_nao_grava_metas_nem_cria_nada(tmp_path, settings):
    c = db.connect(tmp_path / "vazio.db")
    now = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
    assert universe.universe_due(c, now) is False
    out = run(universe.refresh_universe(c, settings, sleep=Sleeps()))
    assert out == {"updated": 0, "skipped": 0, "failed": 0, "aborted": False}
    assert db.get_meta(c, "universe_attempt_at") is None and db.get_meta(c, "universe_refreshed_at") is None
    assert db.list_assets(c, watch=None) == []
    run(catalog.refresh_catalog(c, settings))  # o catálogo chega
    assert universe.universe_due(c, now) is True
    assert run(universe.refresh_universe(c, settings, sleep=Sleeps()))["updated"] == 16


def test_purge_com_catalogo_vazio_nao_apaga(tmp_path):
    c = db.connect(tmp_path / "vazio.db")
    aid = db.add_asset(c, "ANTIGO1", "B3", watch=False)
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    c.execute("UPDATE assets SET last_viewed = ? WHERE id = ?", ((now - timedelta(days=90)).isoformat(), aid))
    c.commit()
    assert universe.purge(c, now) == 0
    assert db.get_asset(c, aid) is not None


def test_passada_sem_nada_a_fazer_nao_grava_conclusao(conn, settings):
    run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    conn.execute("DELETE FROM meta WHERE key = 'universe_refreshed_at'")
    conn.commit()
    monkey = universe._universe_assets
    universe._universe_assets = lambda c: []
    try:
        run(universe.refresh_universe(conn, settings, sleep=Sleeps()))
    finally:
        universe._universe_assets = monkey
    assert db.get_meta(conn, "universe_refreshed_at") is None
