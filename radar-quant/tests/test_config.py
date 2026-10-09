import pytest

from app.config import get_settings, normalize_symbol


def test_normalize_symbol():
    assert normalize_symbol(" petr4 ", "B3") == "PETR4"
    assert normalize_symbol("PETR4.SA", "B3") == "PETR4"
    assert normalize_symbol("btcusdt", "CRYPTO") == "BTC"
    assert normalize_symbol("BTC-USD", "CRYPTO") == "BTC"


def test_normalize_symbol_vazio():
    with pytest.raises(ValueError):
        normalize_symbol("  ", "US")


def test_get_settings_le_ambiente(monkeypatch, tmp_path):
    monkeypatch.setenv("RADAR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_PROVIDER", "synthetic")
    monkeypatch.setenv("RADAR_REFRESH_HOURS", "2.5")
    s = get_settings()
    assert s.data_dir == tmp_path and s.provider == "synthetic" and s.refresh_hours == 2.5


def test_get_settings_padroes(monkeypatch):
    for k in ("RADAR_DATA_DIR", "RADAR_PROVIDER", "RADAR_REFRESH_HOURS"):
        monkeypatch.delenv(k, raising=False)
    s = get_settings()
    assert str(s.data_dir) == "/app/data" and s.provider == "live" and s.refresh_hours == 6


@pytest.mark.parametrize("symbol,market,esperado", [
    ("BRK.B", "US", "BRK.B"), ("^BVSP", "B3", "^BVSP"), ("brk-b", "US", "BRK-B"),
    ("EURUSD=X", "US", "EURUSD=X"), ("A" * 20, "US", "A" * 20)])
def test_normalize_symbol_aceita_formatos_reais(symbol, market, esperado):
    assert normalize_symbol(symbol, market) == esperado


@pytest.mark.parametrize("symbol", ["AB\x00CD", "../../x", "../../../v1/test?x=1#f", "A" * 100, "A" * 21,
                                    "AB CD", "PETR4\nX", ".SA", "-X", "AÇÃO", "A/B", "A%2FB"])
def test_normalize_symbol_rejeita_invalidos(symbol):
    with pytest.raises(ValueError, match="símbolo inválido"):
        normalize_symbol(symbol, "US")
