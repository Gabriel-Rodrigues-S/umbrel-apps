"""Testes do módulo de curto prazo (swing): sinais, simulação, estatísticas e evidência."""
import json

import numpy as np
import pandas as pd
import pytest

from app.stats import swing

KEYS = list(swing.SETUPS)


def make_df(close, open_=None, high=None, low=None, volume=None, start="2020-01-01"):
    close = np.asarray(close, dtype=float)
    n = len(close)
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({
        "open": close if open_ is None else np.asarray(open_, dtype=float),
        "high": close if high is None else np.asarray(high, dtype=float),
        "low": close if low is None else np.asarray(low, dtype=float),
        "close": close,
        "volume": np.full(n, 1000.0) if volume is None else np.asarray(volume, dtype=float),
    }, index=idx)


def random_df(n=600, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, n)))
    opens = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(close, opens) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(close, opens) * (1 - np.abs(rng.normal(0, 0.005, n)))
    return make_df(close, opens, high, low, rng.integers(500, 1500, n).astype(float))


def trade(excess, day=0, net=None):
    d = pd.Timestamp("2021-03-01") + pd.Timedelta(days=day)
    return swing.Trade(d, 100.0, d + pd.Timedelta(days=3), 101.0, 3,
                       excess if net is None else net, excess)


def fake_signals(monkeypatch, n, entries, exits=()):
    ent = pd.Series(False, index=range(n))
    ex = pd.Series(False, index=range(n))
    ent.iloc[list(entries)] = True
    ex.iloc[list(exits)] = True

    def fake(df, key):
        return ent.set_axis(df.index), ex.set_axis(df.index)
    monkeypatch.setattr(swing, "signals", fake)


def sim_df(n=30):
    i = np.arange(n)
    return make_df(100 + i + 0.5, open_=100 + i)


# --- sinais ---------------------------------------------------------------

@pytest.mark.parametrize("key", KEYS)
def test_signals_sem_antecipacao(key):
    df = random_df()
    ent, ex = swing.signals(df, key)
    ent4, ex4 = swing.signals(df.iloc[:400], key)
    assert ent.iloc[:400].equals(ent4) and ex.iloc[:400].equals(ex4)
    alt = df.copy()
    alt.iloc[-1] = alt.iloc[-1] * 3
    ent2, ex2 = swing.signals(alt, key)
    assert ent.iloc[:-1].equals(ent2.iloc[:-1]) and ex.iloc[:-1].equals(ex2.iloc[:-1])


def test_signals_chave_invalida():
    with pytest.raises(ValueError):
        swing.signals(random_df(50), "xyz")


def _flat_breakout(vol_mult):
    close = np.full(60, 100.0)
    close[40] = 105.0
    vol = np.full(60, 1000.0)
    vol[40] = 1000.0 * vol_mult
    return make_df(close, volume=vol)


def test_rompimento_volume_2x_entra_so_nesse_dia():
    ent, _ = swing.signals(_flat_breakout(2.0), "rompimento")
    assert list(np.flatnonzero(ent.to_numpy())) == [40]


def test_rompimento_volume_1_2x_nao_entra():
    ent, _ = swing.signals(_flat_breakout(1.2), "rompimento")
    assert not ent.any()


def test_rompimento_volume_zero():
    close = np.full(60, 100.0)
    close[40] = 105.0
    ent, ex = swing.signals(make_df(close, volume=np.zeros(60)), "rompimento")
    assert not ent.any()


def test_reversao_entra_acima_da_sma200_e_nao_abaixo():
    up = 100 + 0.5 * np.arange(300)
    up = np.concatenate([up, [up[-1] - 8, up[-1] - 16]])
    ent, _ = swing.signals(make_df(up), "reversao")
    assert ent.iloc[-2:].any() and not ent.iloc[:-2].any()
    down = 300 - 0.5 * np.arange(300)
    down = np.concatenate([down, [down[-1] - 8, down[-1] - 16]])
    ent2, _ = swing.signals(make_df(down), "reversao")
    assert not ent2.any()


def test_queda_extrema_dispara_e_sai_na_media():
    base = 100 + np.arange(300.0)
    close = np.concatenate([base, [base[-1] - 25]])
    ent, _ = swing.signals(make_df(close), "queda")
    assert ent.iloc[-1] and not ent.iloc[:-1].any()
    close2 = np.concatenate([close, [base[-1] + 50]])
    _, ex = swing.signals(make_df(close2), "queda")
    assert ex.iloc[-1]


def test_preco_constante_sem_sinais_e_relatorio_valido():
    df = make_df(np.full(600, 123.45))
    for k in KEYS:
        ent, _ = swing.signals(df, k)
        assert not ent.any()
    rep = swing.swing_report(df)
    txt = json.dumps(rep, allow_nan=False)
    assert "NaN" not in txt and "Infinity" not in txt
    assert all(s["stats"]["trades"] == 0 and s["state"] == "nenhum" for s in rep["setups"])


# --- simulação ------------------------------------------------------------

def test_simulate_entrada_e_saida_na_abertura(monkeypatch):
    df = sim_df()
    fake_signals(monkeypatch, 30, entries=[3], exits=[6])
    trades, pos = swing.simulate(df, "reversao")
    assert pos is None and len(trades) == 1
    t = trades[0]
    assert t.entry_date == df.index[4] and t.entry_price == 104.0
    assert t.exit_date == df.index[7] and t.exit_price == 107.0
    assert t.days == 3
    assert t.net == pytest.approx(107 / 104 - 1 - 0.002)


def test_simulate_limite_de_10_pregoes_sai_no_fechamento(monkeypatch):
    df = sim_df()
    fake_signals(monkeypatch, 30, entries=[3])
    trades, pos = swing.simulate(df, "reversao")
    t = trades[0]
    assert t.days == 10 and t.exit_date == df.index[13] and t.exit_price == 113.5
    assert t.net == pytest.approx(113.5 / 104 - 1 - 0.002)
    assert pos is None


def test_simulate_segunda_entrada_na_posicao_ignorada(monkeypatch):
    fake_signals(monkeypatch, 30, entries=[3, 5], exits=[8])
    trades, _ = swing.simulate(sim_df(), "reversao")
    assert len(trades) == 1 and trades[0].entry_date == sim_df().index[4]


def test_simulate_reentrada_depois_da_saida(monkeypatch):
    fake_signals(monkeypatch, 30, entries=[3, 12], exits=[6])
    trades, _ = swing.simulate(sim_df(), "reversao")
    assert [t.entry_price for t in trades] == [104.0, 113.0]


def test_simulate_sinal_no_ultimo_candle(monkeypatch):
    fake_signals(monkeypatch, 30, entries=[29])
    trades, pos = swing.simulate(sim_df(), "reversao")
    assert trades == [] and pos is None
    assert swing.setup_report(sim_df(), "reversao")["state"] == "sinal"


def test_simulate_posicao_aberta_no_fim(monkeypatch):
    df = sim_df()
    fake_signals(monkeypatch, 30, entries=[25])
    trades, pos = swing.simulate(df, "reversao")
    assert trades == []
    assert pos["days"] == 4 and pos["entry_price"] == 126.0
    assert pos["entry_date"] == df.index[26].isoformat()
    assert pos["ret"] == pytest.approx(129.5 / 126.0 - 1)
    rep = swing.setup_report(df, "reversao")
    assert rep["state"] == "posicao" and rep["position"]["days"] == 4
    assert rep["markers"][-1]["type"] == "entry"


def test_simulate_excesso_desconta_buy_and_hold(monkeypatch):
    df = sim_df()
    fake_signals(monkeypatch, 30, entries=[3], exits=[6])
    t = swing.simulate(df, "reversao")[0][0]
    mu = np.log(df.close / df.close.shift(1)).dropna().mean()
    assert t.excess == pytest.approx(t.net - (np.exp(mu * 3) - 1))


# --- estatísticas ---------------------------------------------------------

def test_trade_stats_vazio():
    s = swing.trade_stats([])
    assert s["trades"] == 0 and s["evidence"] == "amostra_insuficiente"
    assert all(v is None for k, v in s.items() if k not in ("trades", "evidence"))


def test_trade_stats_amostra_pequena():
    s = swing.trade_stats([trade(0.01, i) for i in range(5)])
    assert s["trades"] == 5 and s["ci_low"] is None and s["ci_high"] is None
    assert s["evidence"] == "amostra_insuficiente" and s["mean_excess"] == pytest.approx(0.01)


def test_trade_stats_favoravel_e_contraria():
    s = swing.trade_stats([trade(0.01, i) for i in range(30)])
    assert s["evidence"] == "favoravel" and s["ci_low"] == s["ci_high"] == 0.01
    s = swing.trade_stats([trade(-0.01, i) for i in range(30)])
    assert s["evidence"] == "contraria"


def test_trade_stats_sem_evidencia_e_determinismo():
    ts = [trade(0.05 if i % 2 else -0.05, i) for i in range(30)]
    a, b = swing.trade_stats(ts), swing.trade_stats(ts)
    assert a == b and a["evidence"] == "sem_evidencia"
    assert a["ci_low"] < 0 < a["ci_high"]
    assert a["win_rate"] == 0.5


# --- relatório e contexto -------------------------------------------------

def test_setup_report_formato():
    df = random_df(800, seed=3)
    for k in KEYS:
        r = swing.setup_report(df, k)
        assert set(r) == {"key", "label", "description", "state", "position", "stats", "markers", "pool"}
        assert r["key"] == k and r["label"] == swing.SETUPS[k]["label"]
        times = [m["time"] for m in r["markers"]]
        assert times == sorted(times) and len(r["markers"]) <= swing.MAX_MARKERS
        assert all(isinstance(p[0], int) and 200000 < p[0] < 300000 for p in r["pool"])
        assert len(r["pool"]) == r["stats"]["trades"]
        json.dumps(r, allow_nan=False)


def test_setup_report_chave_invalida():
    with pytest.raises(ValueError):
        swing.setup_report(random_df(50), "xyz")


def test_markers_limitados_a_200(monkeypatch):
    n = 1200
    fake_signals(monkeypatch, n, entries=range(2, n, 4), exits=range(4, n, 4))
    r = swing.setup_report(sim_df(n), "reversao")
    assert len(r["markers"]) == swing.MAX_MARKERS


def test_context_atr_e_volume():
    n = 60
    df = make_df(np.full(n, 100.0), high=np.full(n, 101.0), low=np.full(n, 99.0))
    c = swing.context(df)
    assert set(c) == {"atr_pct", "range_5d", "rel_volume", "dist_high20", "dist_low20"}
    assert c["atr_pct"] == pytest.approx(0.02)
    assert c["rel_volume"] == pytest.approx(1.0)
    assert c["dist_high20"] == pytest.approx(100 / 101 - 1, abs=1e-6)
    assert c["dist_low20"] == pytest.approx(100 / 99 - 1, abs=1e-6)
    assert c["range_5d"] == 0.0


def test_context_volume_zero():
    c = swing.context(make_df(np.full(60, 100.0), volume=np.zeros(60)))
    assert c["rel_volume"] is None
    json.dumps(c, allow_nan=False)


def test_swing_report_ordem():
    rep = swing.swing_report(random_df(400))
    assert [s["key"] for s in rep["setups"]] == KEYS
    assert "atr_pct" in rep["context"]
    json.dumps(rep, allow_nan=False)


# --- evidência agregada ---------------------------------------------------

def test_pooled_poucas_operacoes():
    p = swing.pooled_evidence([(202001, 0.01)] * 50)
    assert p["trades"] == 50 and p["ci_low"] is None
    assert p["evidence"] == "amostra_insuficiente"


def _pool(n_months=30, per=10, ex=0.005):
    return [(202001 + (m // 12) * 100 + m % 12, ex) for m in range(n_months) for _ in range(per)]


def test_pooled_favoravel_e_deterministico():
    pool = _pool()
    a = swing.pooled_evidence(pool)
    assert a["trades"] == 300 and a["evidence"] == "favoravel"
    assert a["ci_low"] == a["ci_high"] == 0.005 and a["win_rate"] == 1.0
    assert a == swing.pooled_evidence(pool)


def test_pooled_mes_unico_sem_erro():
    p = swing.pooled_evidence([(202001, 0.01 if i % 2 else -0.01) for i in range(120)])
    assert p["ci_low"] == p["ci_high"] == p["mean_excess"]
    assert p["evidence"] == "sem_evidencia"


def test_pooled_vazio():
    p = swing.pooled_evidence([])
    assert p["trades"] == 0 and p["evidence"] == "amostra_insuficiente"
    json.dumps(p, allow_nan=False)
