import asyncio
from datetime import datetime, timezone

import pandas as pd
import pytest

from app import db, service
from app.config import DEFAULT_WATCHLIST, Settings
from app.providers.base import Bar, Candle, ProviderError, UnknownSymbol
from app.providers.synthetic import SyntheticProvider


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "radar.db")


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, provider="synthetic", refresh_hours=6)


class Quebrado:
    def __init__(self, exc):
        self.exc = exc

    async def fetch_daily(self, symbol, market):
        raise self.exc


def test_seed_watchlist_idempotente(conn):
    service.seed_watchlist(conn)
    service.seed_watchlist(conn)
    assert len(db.list_assets(conn)) == len(DEFAULT_WATCHLIST) == 13


def test_refresh_all_grava_candles(conn, settings):
    service.seed_watchlist(conn)
    asyncio.run(service.refresh_all(conn, settings))
    for a in db.list_assets(conn):
        df = service.load_frame(conn, a["id"])
        assert len(df) == 1500 and a["last_error"] is None
        assert isinstance(df.index, pd.DatetimeIndex) and df.index.is_monotonic_increasing
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_refresh_all_isola_falha(conn, settings):
    ok = db.add_asset(conn, "PETR4", "B3")
    bad = db.add_asset(conn, "FALHA1", "B3")
    asyncio.run(service.refresh_all(conn, settings))
    assert len(db.load_candles(conn, ok)) == 1500
    assert db.get_asset(conn, ok)["last_error"] is None
    assert "indisponível" in db.get_asset(conn, bad)["last_error"]
    assert db.load_candles(conn, bad) == []


def test_falha_preserva_candles_antigos(conn, settings):
    a = db.add_asset(conn, "PETR4", "B3")
    db.upsert_candles(conn, a, [Candle("2024-01-02", 1, 1, 1, 1, 1)])
    asset = db.get_asset(conn, a)
    asyncio.run(service.refresh_asset(conn, asset, settings, provider=Quebrado(ProviderError("fora do ar"))))
    assert len(db.load_candles(conn, a)) == 1
    assert db.get_asset(conn, a)["last_error"] == "fora do ar"


def test_unknown_symbol_relanca_e_grava(conn, settings):
    a = db.add_asset(conn, "INVALID1", "US")
    with pytest.raises(UnknownSymbol):
        asyncio.run(service.refresh_asset(conn, db.get_asset(conn, a), settings))
    assert db.get_asset(conn, a)["last_error"] == "símbolo não encontrado"


class Fixo:
    def __init__(self, candles):
        self.candles = candles

    async def fetch_daily(self, symbol, market):
        return self.candles


def test_refresh_descarta_historico_que_saiu_da_janela(conn, settings):
    # split 10:1 com a janela já andada: as linhas antigas (fator antigo) não podem sobrar
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [Candle(d, 100, 100, 100, 100, 1) for d in ("2024-01-02", "2024-01-03")])
    dias = pd.bdate_range("2024-01-04", periods=300).strftime("%Y-%m-%d")
    novo = Fixo([Candle(d, 10, 10, 10, 10, 1) for d in dias])
    asyncio.run(service.refresh_asset(conn, db.get_asset(conn, a), settings, provider=novo))
    assert service.load_frame(conn, a)["close"].tolist() == [10] * 300


def test_refresh_all_nao_para_em_unknown_symbol(conn, settings):
    db.add_asset(conn, "INVALID1", "US")
    ok = db.add_asset(conn, "AAPL", "US")
    asyncio.run(service.refresh_all(conn, settings))
    assert len(db.load_candles(conn, ok)) == 1500


def test_resample_semanal_e_mensal():
    idx = pd.bdate_range("2024-01-01", periods=10)
    df = pd.DataFrame({"open": range(10, 20), "high": range(20, 30), "low": range(0, 10),
                       "close": range(100, 110), "volume": [1.0] * 10}, index=idx)
    w = service.resample(df, "1wk")
    assert len(w) == 2
    assert w.iloc[0]["open"] == 10 and w.iloc[0]["close"] == 104 and w.iloc[0]["volume"] == 5
    assert w.iloc[0]["high"] == 24 and w.iloc[0]["low"] == 0
    # cada balde leva a última data real de pregão, não o fim do período
    assert [d.strftime("%Y-%m-%d") for d in w.index] == ["2024-01-05", "2024-01-12"]
    m = service.resample(df, "1mo")
    assert len(m) == 1 and m.index[0] == idx[-1]
    parcial = service.resample(df.iloc[:8], "1wk")  # semana corrente ainda na quarta-feira
    assert len(parcial) == 2 and parcial.index[-1] == idx[7] and parcial.iloc[-1]["close"] == 107
    assert service.resample(df.iloc[:0], "1wk").empty
    assert service.resample(df, "1d") is df
    with pytest.raises(ValueError):
        service.resample(df, "2h")


def test_load_rf_series(conn):
    assert service.load_rf_series(conn).empty
    db.upsert_rf(conn, [("2024-01-03", 0.0004), ("2024-01-02", 0.0005)])
    rf = service.load_rf_series(conn)
    assert isinstance(rf.index, pd.DatetimeIndex) and rf.iloc[0] == 0.0005


# ---------- 1.1: intervalos derivados do diário ----------

def _tres_anos():
    idx = pd.bdate_range("2022-01-03", "2024-12-31")
    n = len(idx)
    return pd.DataFrame({"open": range(n), "high": [x + 5 for x in range(n)], "low": [x - 5 for x in range(n)],
                         "close": [x + 1 for x in range(n)], "volume": [2.0] * n}, index=idx)


@pytest.mark.parametrize("interval,n", [("3mo", 12), ("6mo", 6), ("1y", 3)])
def test_resample_civil(interval, n):
    df = _tres_anos()
    r = service.resample(df, interval)
    assert len(r) == n and r.index[-1] == df.index[-1]
    assert r.iloc[0]["open"] == df.iloc[0]["open"] and r.iloc[-1]["close"] == df.iloc[-1]["close"]
    primeiro = df[df.index.year == 2022] if interval == "1y" else df[df.index <= r.index[0]]
    assert r.index[0] == primeiro.index[-1] and r.iloc[0]["volume"] == 2.0 * len(primeiro)
    assert r.iloc[0]["high"] == primeiro["high"].max() and r.iloc[0]["low"] == primeiro["low"].min()
    assert service.resample(df.iloc[:0], interval).empty


def test_resample_semestre_fecha_em_junho():
    r = service.resample(_tres_anos(), "6mo")
    assert [d.month for d in r.index[:2]] == [6, 12]


def test_resample_intraday_invalido():
    with pytest.raises(ValueError):
        service.resample(_tres_anos(), "5m")


# ---------- 1.1: agregação e intraday ----------

def _bar(t, o, h, l, c, v):
    return Bar(t, o, h, l, c, v)


def test_aggregate_bars():
    bars = [_bar(1260 + 60 * i, 10 + i, 20 + i, 5 - i, 11 + i, 1.0) for i in range(6)]  # 1260 = 7 * 180
    a, b = service.aggregate_bars(bars, 180)
    assert (a.time, a.open, a.high, a.low, a.close, a.volume) == (1260, 10, 22, 3, 13, 3.0)
    assert (b.time, b.open, b.high, b.low, b.close, b.volume) == (1440, 13, 25, 0, 16, 3.0)


def test_aggregate_bars_buraco():
    bars = [_bar(1260, 1, 2, 0, 1, 1), _bar(1320, 1, 3, 0, 2, 1), _bar(1620, 5, 6, 4, 5, 1)]  # pula 1380..1560
    out = service.aggregate_bars(bars, 180)
    assert [b.time for b in out] == [1260, 1620] and out[0].volume == 2


class Contador:
    """Provider de teste: conta chamadas e só entrega nativamente o que `native` diz."""
    def __init__(self, native=("1m", "5m", "30m", "1h"), erro=None):
        self.NATIVE_INTRADAY = frozenset(native)
        self.calls = []
        self.erro = erro

    async def fetch_intraday(self, symbol, market, interval):
        self.calls.append((symbol, interval))
        if self.erro:
            raise self.erro
        step = {"1m": 60, "3m": 180, "5m": 300, "30m": 1800, "1h": 3600}[interval]
        return [Bar(1260 + step * i, 1.0 + i, 2.0 + i, 0.5, 1.5 + i, 10.0) for i in range(12)], 15


@pytest.fixture(autouse=True)
def _limpa_intraday():
    service.clear_intraday_cache()
    yield
    service.clear_intraday_cache()


def _ativo(i, symbol="PETR4", market="B3"):
    return {"id": i, "symbol": symbol, "market": market}


def test_load_intraday_nativo_e_ttl(settings, monkeypatch):
    t = [100.0]
    monkeypatch.setattr(service, "_clock", lambda: t[0])
    p = Contador()
    r = asyncio.run(service.load_intraday(_ativo(1), "1m", settings, provider=p))
    assert len(r["bars"]) == 12 and r["delay_minutes"] == 15 and r["fetched_at"]
    asyncio.run(service.load_intraday(_ativo(1), "1m", settings, provider=p))
    assert len(p.calls) == 1
    t[0] += 56  # TTL do 1m = 55 s
    asyncio.run(service.load_intraday(_ativo(1), "1m", settings, provider=p))
    assert len(p.calls) == 2
    asyncio.run(service.load_intraday(_ativo(1), "30m", settings, provider=p))
    t[0] += 299
    asyncio.run(service.load_intraday(_ativo(1), "30m", settings, provider=p))
    assert len(p.calls) == 3


def test_load_intraday_sintetico(settings):
    r = asyncio.run(service.load_intraday(_ativo(1), "1m", settings))
    assert len(r["bars"]) == 1500 and r["delay_minutes"] is None


def test_load_intraday_deriva_3m_e_10m(settings):
    p = Contador()
    r = asyncio.run(service.load_intraday(_ativo(1), "3m", settings, provider=p))
    assert p.calls == [("PETR4", "1m")] and len(r["bars"]) == 4
    assert all(b.time % 180 == 0 for b in r["bars"])
    r = asyncio.run(service.load_intraday(_ativo(1), "10m", settings, provider=p))
    assert p.calls[-1] == ("PETR4", "5m") and all(b.time % 600 == 0 for b in r["bars"])


def test_load_intraday_chave_separa_ativo_e_intervalo(settings):
    p = Contador()
    for a, i in ((1, "1m"), (2, "1m"), (1, "5m"), (1, "1m")):
        asyncio.run(service.load_intraday(_ativo(a), i, settings, provider=p))
    assert len(p.calls) == 3


def test_load_intraday_erro_nao_cacheia(settings):
    p = Contador(erro=ProviderError("fora"))
    for _ in range(2):
        with pytest.raises(ProviderError):
            asyncio.run(service.load_intraday(_ativo(1), "1m", settings, provider=p))
    assert len(p.calls) == 2
    p = Contador(erro=UnknownSymbol("x"))
    with pytest.raises(UnknownSymbol):
        asyncio.run(service.load_intraday(_ativo(2), "1m", settings, provider=p))


def test_load_intraday_intervalo_invalido(settings):
    with pytest.raises(ValueError):
        asyncio.run(service.load_intraday(_ativo(1), "1d", settings, provider=Contador()))


def test_load_intraday_limite_de_64(settings):
    p = Contador()
    for i in range(65):
        asyncio.run(service.load_intraday(_ativo(i), "1m", settings, provider=p))
    assert len(service._intraday_cache) == 64
    n = len(p.calls)
    asyncio.run(service.load_intraday(_ativo(0), "1m", settings, provider=p))  # a mais antiga saiu
    assert len(p.calls) == n + 1
    asyncio.run(service.load_intraday(_ativo(64), "1m", settings, provider=p))  # a mais nova ficou
    assert len(p.calls) == n + 1


# ---------- 1.1: abrir ativo ----------

class DiarioContado:
    def __init__(self):
        self.n = 0
        self.inner = SyntheticProvider()

    async def fetch_daily(self, symbol, market):
        self.n += 1
        return await self.inner.fetch_daily(symbol, market)


def test_open_asset_cria_watch0_e_nao_refaz(conn, settings, monkeypatch):
    p = DiarioContado()
    monkeypatch.setattr(service, "get_provider", lambda market, s: p)
    a = asyncio.run(service.open_asset(conn, " tsla ", "US", settings))
    assert a["symbol"] == "TSLA" and a["watch"] == 0 and a["last_viewed"]
    assert len(db.load_candles(conn, a["id"])) == 1500 and p.n == 1
    visto = a["last_viewed"]
    b = asyncio.run(service.open_asset(conn, "TSLA", "US", settings))
    assert p.n == 1 and b["id"] == a["id"] and b["last_viewed"] >= visto


def test_open_asset_atualiza_se_velho_ou_sem_candles(conn, settings, monkeypatch):
    p = DiarioContado()
    monkeypatch.setattr(service, "get_provider", lambda market, s: p)
    a = asyncio.run(service.open_asset(conn, "TSLA", "US", settings))
    conn.execute("UPDATE assets SET last_refresh = '2020-01-01T00:00:00+00:00' WHERE id = ?", (a["id"],))
    conn.commit()
    asyncio.run(service.open_asset(conn, "TSLA", "US", settings))
    assert p.n == 2


def test_stale_por_idade_e_por_corte():
    t = lambda d, h, m=0: datetime(2026, 10, d, h, m, tzinfo=timezone.utc)  # noqa: E731
    assert service._stale(None, t(9, 12)) is True
    assert service._stale(t(8, 15).isoformat(), t(9, 5, 30)) is True  # aberto no pregão, lido depois do corte
    assert service._stale(t(9, 3).isoformat(), t(9, 5, 30)) is True  # 2 h 30, mas anterior ao corte das 05:00
    assert service._stale(t(9, 3).isoformat(), t(9, 4, 59)) is False
    assert service._stale(t(9, 5, 10).isoformat(), t(9, 5, 30)) is False
    assert service._stale(t(9, 5, 10).isoformat(), t(9, 11, 9)) is False
    assert service._stale(t(9, 5, 10).isoformat(), t(9, 11, 11)) is True  # mais de 6 h
    assert service._stale(t(9, 15).isoformat()) in (True, False)  # sem `now`: relógio real


def test_cutoff():
    t = lambda d, h, m=0: datetime(2026, 10, d, h, m, tzinfo=timezone.utc)  # noqa: E731
    assert service.cutoff(t(9, 4, 59)) == t(8, 5)
    assert service.cutoff(t(9, 5)) == t(9, 5)
    assert service.cutoff(t(9, 23, 59)) == t(9, 5)


def test_open_asset_watchlist_continua_watch1(conn, settings, monkeypatch):
    monkeypatch.setattr(service, "get_provider", lambda market, s: DiarioContado())
    db.add_asset(conn, "PETR4", "B3")
    a = asyncio.run(service.open_asset(conn, "petr4", "B3", settings))
    assert a["watch"] == 1 and a["last_viewed"]


def test_open_asset_invalido_nao_grava(conn, settings):
    with pytest.raises(UnknownSymbol):
        asyncio.run(service.open_asset(conn, "INVALIDO", "US", settings))
    assert db.find_asset(conn, "INVALIDO", "US") is None


def test_open_asset_erro_inesperado_apaga(conn, settings, monkeypatch):
    class Bomba:
        async def fetch_daily(self, symbol, market):
            raise RuntimeError("bum")
    monkeypatch.setattr(service, "get_provider", lambda market, s: Bomba())
    with pytest.raises(RuntimeError):
        asyncio.run(service.open_asset(conn, "TSLA", "US", settings))
    assert db.find_asset(conn, "TSLA", "US") is None


def test_open_asset_simbolo_malformado(conn, settings):
    with pytest.raises(ValueError):
        asyncio.run(service.open_asset(conn, "a/b", "US", settings))


def test_refresh_all_so_watchlist(conn, settings):
    w = db.add_asset(conn, "PETR4", "B3")
    c = db.add_asset(conn, "TSLA", "US", watch=False)
    asyncio.run(service.refresh_all(conn, settings))
    assert len(db.load_candles(conn, w)) == 1500 and db.load_candles(conn, c) == []


# ---------- 1.1: abrir ativo com a fonte fora do ar ----------

class ForaDoAr:
    async def fetch_daily(self, symbol, market):
        raise ProviderError("fonte fora do ar")


def test_open_asset_novo_com_fonte_fora_nao_deixa_orfao(conn, settings, monkeypatch):
    monkeypatch.setattr(service, "get_provider", lambda market, s: ForaDoAr())
    with pytest.raises(ProviderError, match="fonte fora do ar"):
        asyncio.run(service.open_asset(conn, "TSLA", "US", settings))
    assert db.find_asset(conn, "TSLA", "US") is None


def test_open_asset_existente_sem_candles_levanta_sem_apagar(conn, settings, monkeypatch):
    monkeypatch.setattr(service, "get_provider", lambda market, s: ForaDoAr())
    a = db.add_asset(conn, "TSLA", "US", watch=False)
    with pytest.raises(ProviderError, match="fonte fora do ar"):
        asyncio.run(service.open_asset(conn, "TSLA", "US", settings))
    assert db.get_asset(conn, a) is not None


def test_open_asset_simultaneo_atualiza_uma_vez(conn, settings, monkeypatch):
    p = DiarioContado()
    monkeypatch.setattr(service, "get_provider", lambda market, s: p)

    async def duas():
        return await asyncio.gather(service.open_asset(conn, "TSLA", "US", settings),
                                    service.open_asset(conn, "TSLA", "US", settings))
    a, b = asyncio.run(duas())
    assert a["id"] == b["id"] and p.n == 1 and len(db.list_assets(conn, watch=None)) == 1
    assert service._open_locks == {}
