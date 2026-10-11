import pandas as pd
import pytest

from app import db
from app.providers.base import Candle


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "sub" / "radar.db")


def c(date, close):
    return Candle(date, close, close, close, close, 1.0)


def test_add_e_list(conn):
    a = db.add_asset(conn, "PETR4", "B3")
    b = db.add_asset(conn, "AAPL", "US")
    rows = db.list_assets(conn)
    assert [r["id"] for r in rows] == [a, b]
    assert rows[0]["currency"] == "BRL" and rows[1]["currency"] == "USD"
    assert rows[1]["position"] == rows[0]["position"] + 1
    assert db.get_asset(conn, a)["symbol"] == "PETR4"
    assert db.get_asset(conn, 999) is None


def test_duplicado(conn):
    db.add_asset(conn, "PETR4", "B3")
    with pytest.raises(db.DuplicateAsset):
        db.add_asset(conn, "PETR4", "B3")


def test_upsert_candles_substitui_e_ordena(conn):
    a = db.add_asset(conn, "AAPL", "US")
    assert db.upsert_candles(conn, a, [c("2024-01-03", 3), c("2024-01-02", 2)]) == 2
    db.upsert_candles(conn, a, [c("2024-01-02", 9)])
    rows = db.load_candles(conn, a)
    assert [r["date"] for r in rows] == ["2024-01-02", "2024-01-03"]
    assert rows[0]["close"] == 9


def test_delete_remove_candles(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 2)])
    assert db.delete_asset(conn, a) is True
    assert db.load_candles(conn, a) == []
    assert db.get_asset(conn, a) is None
    assert db.delete_asset(conn, a) is False


def test_refresh_status(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.set_refresh_status(conn, a, "falhou")
    r = db.get_asset(conn, a)
    assert r["last_error"] == "falhou" and r["last_refresh"]
    db.set_refresh_status(conn, a, None)
    assert db.get_asset(conn, a)["last_error"] is None


def test_rf_ida_e_volta(conn):
    db.upsert_rf(conn, [("2024-01-03", 0.0004), ("2024-01-02", 0.0003)])
    db.upsert_rf(conn, [("2024-01-02", 0.0005)])
    assert db.load_rf(conn) == [("2024-01-02", 0.0005), ("2024-01-03", 0.0004)]


def _lote(start, n, close):
    return [c(d.strftime("%Y-%m-%d"), close) for d in pd.date_range(start, periods=n)]


def _closes(conn, a):
    return [(r["date"], r["close"]) for r in db.load_candles(conn, a)]


def test_replace_candles_apaga_o_que_saiu_da_janela(conn):
    a, outro = db.add_asset(conn, "AAPL", "US"), db.add_asset(conn, "MSFT", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 100), c("2024-01-03", 100), c("2024-01-04", 100)])
    db.upsert_candles(conn, outro, [c("2024-01-02", 7)])
    # janela reajustada (split 10:1) que já começa depois das duas primeiras datas
    lote = _lote("2024-01-04", db.MIN_TRIM_CANDLES, 10)
    assert db.replace_candles(conn, a, lote[::-1]) == db.MIN_TRIM_CANDLES == 250
    assert _closes(conn, a) == [(x.date, 10) for x in lote]
    assert _closes(conn, outro) == [("2024-01-02", 7)]


def test_replace_candles_lote_curto_nao_apaga_historico(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 100), c("2024-01-03", 100)])
    # resposta curta do provedor: não é uma janela confiável, só faz o upsert
    assert db.replace_candles(conn, a, _lote("2024-01-03", 10, 10)) == 10
    got = _closes(conn, a)
    assert got[:2] == [("2024-01-02", 100), ("2024-01-03", 10)] and len(got) == 11
    assert db.replace_candles(conn, a, _lote("2024-01-04", db.MIN_TRIM_CANDLES - 1, 10)) == 249
    assert _closes(conn, a)[0] == ("2024-01-02", 100)


def test_replace_candles_lista_vazia_nao_apaga(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 2)])
    assert db.replace_candles(conn, a, []) == 0
    assert _closes(conn, a) == [("2024-01-02", 2)]


@pytest.mark.parametrize("write", ["replace_candles", "upsert_candles"])
def test_escrita_de_candles_com_erro_no_meio_nao_muda_nada(conn, write):
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 2), c("2024-01-03", 3)])
    with pytest.raises(Exception):
        # lote grande o bastante para apagar o histórico; a última linha não é gravável
        getattr(db, write)(conn, a, _lote("2024-01-03", 250, 9) + [c("2025-01-01", object())])
    assert not conn.in_transaction
    assert _closes(conn, a) == [("2024-01-02", 2), ("2024-01-03", 3)]


def test_upsert_rf_com_erro_no_meio_nao_muda_nada(conn):
    db.upsert_rf(conn, [("2024-01-02", 0.0003)])
    with pytest.raises(Exception):
        db.upsert_rf(conn, [("2024-01-02", 0.0009), ("2024-01-03", None)])  # rate é NOT NULL
    assert not conn.in_transaction
    assert db.load_rf(conn) == [("2024-01-02", 0.0003)]


def test_delete_asset_com_erro_nao_apaga_candles(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.upsert_candles(conn, a, [c("2024-01-02", 2)])
    conn.execute("CREATE TRIGGER trava BEFORE DELETE ON assets BEGIN SELECT RAISE(ABORT, 'travado'); END")
    with pytest.raises(Exception):
        db.delete_asset(conn, a)
    assert not conn.in_transaction
    assert len(db.load_candles(conn, a)) == 1 and db.get_asset(conn, a)


# ---------- 1.1: watchlist x cache ----------

def test_list_assets_watch(conn):
    a = db.add_asset(conn, "PETR4", "B3")
    b = db.add_asset(conn, "AAPL", "US", watch=False)
    assert [r["id"] for r in db.list_assets(conn)] == [a]
    assert [r["id"] for r in db.list_assets(conn, None)] == [a, b]
    assert [r["id"] for r in db.list_assets(conn, False)] == [b]


def test_find_asset_set_watch_touch_viewed(conn):
    b = db.add_asset(conn, "AAPL", "US", watch=False)
    assert db.find_asset(conn, "AAPL", "US")["id"] == b
    assert db.find_asset(conn, "AAPL", "B3") is None
    assert db.get_asset(conn, b)["watch"] == 0 and db.get_asset(conn, b)["last_viewed"] is None
    db.touch_viewed(conn, b)
    assert db.get_asset(conn, b)["last_viewed"]
    db.set_watch(conn, b, True)
    assert db.get_asset(conn, b)["watch"] == 1
    assert [r["id"] for r in db.list_assets(conn)] == [b]


def test_delete_asset_apaga_screener_e_news(conn):
    a = db.add_asset(conn, "AAPL", "US")
    k = db.add_asset(conn, "MSFT", "US")
    for x in (a, k):
        db.upsert_screener(conn, x, "2024-01-02", {"score": 1})
        db.replace_news(conn, x, [{"title": "t", "url": "http://x/1", "source": "s", "published_at": "2024-01-01"}])
    assert db.delete_asset(conn, a) is True
    assert [r["asset_id"] for r in db.load_screener(conn)] == [k]
    assert db.load_news(conn, a) == ([], None)
    assert len(db.load_news(conn, k)[0]) == 1


def test_purge_viewed(conn):
    velho = db.add_asset(conn, "OLD", "US", watch=False)
    nunca = db.add_asset(conn, "NEVER", "US", watch=False)
    mantido = db.add_asset(conn, "KEEP", "US", watch=False)
    recente = db.add_asset(conn, "NEW", "US", watch=False)
    wl = db.add_asset(conn, "WL", "US")
    conn.execute("UPDATE assets SET last_viewed='2024-01-01T00:00:00' WHERE id IN (?,?,?)", (velho, mantido, wl))
    conn.execute("UPDATE assets SET last_viewed='2024-06-01T00:00:00' WHERE id=?", (recente,))
    conn.commit()
    db.upsert_candles(conn, velho, [c("2024-01-02", 1)])
    assert db.purge_viewed(conn, "2024-03-01T00:00:00", {mantido}) == 2
    ids = {r["id"] for r in db.list_assets(conn, None)}
    assert ids == {mantido, recente, wl}
    assert db.load_candles(conn, velho) == []


# ---------- 1.1: catálogo ----------

def _catalogo(conn):
    db.replace_catalog_market(conn, "B3", [("PETR4", "Petrobras PN", "Ação"), ("VALE3", "Vale ON", "Ação"),
                                           ("XPET3", "Companhia Petroleo", "Ação"), ("ITUB4", "Itau", "Ação")])


def test_replace_catalog_preserva_indices(conn):
    _catalogo(conn)
    db.set_index_members(conn, "IBOV", "B3", ["PETR4", "VALE3"])
    n = db.replace_catalog_market(conn, "B3", [("PETR4", "Petrobras", "Ação"), ("ABEV3", "Ambev", "Ação")])
    assert n == 2 and db.catalog_count(conn, "B3") == 2
    assert db.catalog_entry(conn, "PETR4", "B3") == {
        "symbol": "PETR4", "market": "B3", "name": "Petrobras", "kind": "Ação", "indices": ["IBOV"]}
    assert db.catalog_entry(conn, "ABEV3", "B3")["indices"] == []
    assert db.catalog_entry(conn, "VALE3", "B3") is None


def test_replace_catalog_nao_mexe_em_outro_mercado(conn):
    _catalogo(conn)
    db.replace_catalog_market(conn, "US", [("AAPL", "Apple", "Ação")])
    db.replace_catalog_market(conn, "B3", [("PETR4", "Petrobras", "Ação")])
    assert db.catalog_count(conn) == 2 and db.catalog_count(conn, "US") == 1


def test_set_index_members(conn):
    _catalogo(conn)
    db.set_index_members(conn, "IBOV", "B3", ["PETR4", "VALE3"])
    db.set_index_members(conn, "IBRA", "B3", ["PETR4", "ITUB4"])
    assert db.catalog_entry(conn, "PETR4", "B3")["indices"] == ["IBOV", "IBRA"]
    # IBOV muda: PETR4 sai do IBOV e continua no IBRA; símbolo ausente é inserido
    assert db.set_index_members(conn, "IBOV", "B3", ["VALE3", "NOVO3"]) == 2
    assert db.catalog_entry(conn, "PETR4", "B3")["indices"] == ["IBRA"]
    novo = db.catalog_entry(conn, "NOVO3", "B3")
    assert novo["name"] == "NOVO3" and novo["kind"] == "Ação" and novo["indices"] == ["IBOV"]
    assert {m["symbol"] for m in db.index_members(conn, "IBRA")} == {"PETR4", "ITUB4"}
    assert {m["symbol"] for m in db.index_members(conn, "IBOV")} == {"VALE3", "NOVO3"}
    assert {m["symbol"] for m in db.index_members(conn)} == {"PETR4", "ITUB4", "VALE3", "NOVO3"}
    assert db.index_members(conn, "IBOV")[0]["market"] == "B3"


def test_search_catalog_ordem_e_limite(conn):
    _catalogo(conn)
    assert [r["symbol"] for r in db.search_catalog(conn, "pet")] == ["PETR4", "XPET3"]
    assert db.search_catalog(conn, "PETR4")[0]["indices"] == []
    assert len(db.search_catalog(conn, "pet", limit=1)) == 1
    assert db.search_catalog(conn, "") == []


@pytest.mark.parametrize("q", ["%", "_", "\\"])
def test_search_catalog_curingas_nao_casam_com_tudo(conn, q):
    _catalogo(conn)
    assert db.search_catalog(conn, q) == []


def test_replace_catalog_lista_vazia_nao_apaga(conn):
    _catalogo(conn)
    db.set_index_members(conn, "IBOV", "B3", ["PETR4"])
    assert db.replace_catalog_market(conn, "B3", []) == 0
    assert db.catalog_count(conn, "B3") == 4
    assert db.catalog_entry(conn, "PETR4", "B3")["indices"] == ["IBOV"]


@pytest.mark.parametrize("q", ["'; DROP TABLE catalog;--", "a" * 500, "  "])
def test_search_catalog_entradas_hostis(conn, q):
    _catalogo(conn)
    r = db.search_catalog(conn, q)
    assert isinstance(r, list) and len(r) < 4
    assert db.catalog_count(conn) == 4


# ---------- 1.1.1: alias (nome completo aprendido) ----------

def test_nome_exibido_e_o_alias_quando_existe(conn):
    _catalogo(conn)
    db.set_index_members(conn, "IBOV", "B3", ["PETR4", "VALE3"])
    assert db.set_alias(conn, "PETR4", "B3", "Petróleo Brasileiro S.A. - Petrobras") is True
    assert db.set_alias(conn, "NADA3", "B3", "Nada") is False
    assert db.catalog_entry(conn, "PETR4", "B3") == {
        "symbol": "PETR4", "market": "B3", "name": "Petróleo Brasileiro S.A. - Petrobras", "kind": "Ação",
        "indices": ["IBOV"]}
    assert db.catalog_entry(conn, "VALE3", "B3")["name"] == "Vale ON"
    assert {m["symbol"]: m["name"] for m in db.index_members(conn, "IBOV")} == {
        "PETR4": "Petróleo Brasileiro S.A. - Petrobras", "VALE3": "Vale ON"}
    achados = db.search_catalog(conn, "brasileiro")
    assert [(r["symbol"], r["name"]) for r in achados] == [("PETR4", "Petróleo Brasileiro S.A. - Petrobras")]


def test_replace_catalog_preserva_alias(conn):
    _catalogo(conn)
    db.set_alias(conn, "PETR4", "B3", "Petrobras completo")
    db.replace_catalog_market(conn, "B3", [("PETR4", "PETROBRAS", "Ação"), ("ABEV3", "AMBEV S.A.", "Ação")])
    assert db.all_catalog(conn) == [
        {"symbol": "ABEV3", "market": "B3", "name": "AMBEV S.A.", "kind": "Ação", "indices": [], "alias": None},
        {"symbol": "PETR4", "market": "B3", "name": "PETROBRAS", "kind": "Ação", "indices": [],
         "alias": "Petrobras completo"}]


def test_upsert_catalog_entry_nao_sobrescreve(conn):
    _catalogo(conn)
    db.set_index_members(conn, "IBOV", "B3", ["PETR4"])
    db.set_alias(conn, "PETR4", "B3", "Petrobras completo")
    db.upsert_catalog_entry(conn, "PETR4", "B3", "Outro nome", "ETF")
    db.upsert_catalog_entry(conn, "NOVO3", "B3", "Novo S.A.", "Ação")
    cat = {c["symbol"]: c for c in db.all_catalog(conn)}
    assert cat["PETR4"] == {"symbol": "PETR4", "market": "B3", "name": "Petrobras PN", "kind": "Ação",
                            "indices": ["IBOV"], "alias": "Petrobras completo"}
    assert cat["NOVO3"] == {"symbol": "NOVO3", "market": "B3", "name": "Novo S.A.", "kind": "Ação",
                            "indices": [], "alias": None}


def test_missing_alias(conn):
    _catalogo(conn)
    db.replace_catalog_market(conn, "US", [("AAPL", "Apple", "Ação")])
    db.set_alias(conn, "VALE3", "B3", "Vale S.A.")
    assert db.missing_alias(conn, "B3") == ["ITUB4", "PETR4", "XPET3"]
    assert db.missing_alias(conn, "B3", ["XPET3", "VALE3", "FORA3", "PETR4", "XPET3"]) == ["XPET3", "PETR4"]
    assert db.missing_alias(conn, "B3", []) == []
    assert db.missing_alias(conn, "US") == ["AAPL"]


# ---------- 1.1: screener, notícias, meta ----------

def test_screener_ida_e_volta(conn):
    a = db.add_asset(conn, "AAPL", "US")
    b = db.add_asset(conn, "MSFT", "US")
    db.upsert_screener(conn, a, "2024-01-02", {"score": 1.5, "setups": {"x": {"state": "nenhum"}}})
    db.upsert_screener(conn, b, "2024-01-02", {"score": 2})
    db.upsert_screener(conn, a, "2024-01-03", {"score": 3})
    todos = db.load_screener(conn)
    assert len(todos) == 2
    ra = next(r for r in todos if r["asset_id"] == a)
    assert ra["as_of"] == "2024-01-03" and ra["payload"] == {"score": 3} and ra["updated_at"]
    assert [r["asset_id"] for r in db.load_screener(conn, [b])] == [b]
    assert db.load_screener(conn, []) == []


def test_load_screener_muitos_ids(conn):
    ids = [db.add_asset(conn, f"S{i}", "US") for i in range(1203)]
    for i in ids[::2]:
        db.upsert_screener(conn, i, "2024-01-02", {"score": i})
    got = db.load_screener(conn, ids + [999999])
    assert [r["asset_id"] for r in got] == ids[::2]
    assert [r["asset_id"] for r in db.load_screener(conn, set(ids[:3]))] == [ids[0], ids[2]]
    assert len(db.load_screener(conn)) == len(ids[::2])


def test_news_ordem_e_fetched_at(conn):
    a = db.add_asset(conn, "AAPL", "US")
    assert db.load_news(conn, a) == ([], None)
    db.replace_news(conn, a, [
        {"title": "velha", "url": "http://x/1", "source": "S", "published_at": "2024-01-01T00:00:00Z"},
        {"title": "nova", "url": "http://x/2", "source": "S", "published_at": "2024-01-02T00:00:00Z"}])
    items, fetched = db.load_news(conn, a)
    assert [i["title"] for i in items] == ["nova", "velha"]
    assert set(items[0]) == {"title", "url", "source", "published_at"} and fetched
    db.replace_news(conn, a, [{"title": "só", "url": "http://x/3", "source": "S", "published_at": "2024-01-03"}])
    assert [i["title"] for i in db.load_news(conn, a)[0]] == ["só"]


def test_news_lista_vazia_grava_fetched_at(conn):
    a = db.add_asset(conn, "AAPL", "US")
    db.replace_news(conn, a, [{"title": "t", "url": "http://x/1", "source": "S", "published_at": "2024-01-01"}])
    db.replace_news(conn, a, [])
    items, fetched = db.load_news(conn, a)
    assert items == [] and fetched


def test_meta(conn):
    assert db.get_meta(conn, "k") is None
    db.set_meta(conn, "k", "1")
    db.set_meta(conn, "k", "2")
    assert db.get_meta(conn, "k") == "2"


def test_touch_news_renova_so_o_carimbo(conn):
    a = db.add_asset(conn, "PETR4", "B3")
    db.replace_news(conn, a, [{"title": "t", "url": "http://x/1", "source": "s", "published_at": "2024-01-01"}])
    db.set_meta(conn, db._news_key(a), "2020-01-01T00:00:00+00:00")
    db.touch_news(conn, a)
    items, fetched = db.load_news(conn, a)
    assert len(items) == 1 and fetched > "2020-01-02"


# ---------- 1.1.1: nomes legíveis ----------

@pytest.mark.parametrize("name, esperado", [
    ("BCO SANTANDER (BRASIL) S.A.", "Bco Santander (Brasil) S.A."),
    ("ISHARES IBOVESPA CLASSE DE ÍNDICE - RESPONSABILIDADE LIMITADA", "Ishares Ibovespa Classe de Índice"),
    ("iShares Ibovespa Classe de Índice - Responsabilidade Limitada", "iShares Ibovespa Classe de Índice"),
    ("PETROLEO BRASILEIRO S.A. PETROBRAS", "Petroleo Brasileiro S.A. Petrobras"),
    ("Apple Inc.", "Apple Inc."), ("WEG S.A.", "Weg S.A."), ("BOVA11", "BOVA11"),
    ("BCO ABC BRASIL S/A", "Bco ABC Brasil S/A"), ("ITAUSA SA", "Itausa SA"), ("CIA BRASILEIRA DE DISTRIBUICAO",
                                                                                "Cia Brasileira de Distribuicao"),
    ("FII KINEA RENDA ETF BDR ON PN UNT B3 BR", "FII Kinea Renda ETF BDR ON PN UNT B3 BR"),
    ("LOJAS DOS SANTOS E DAS FLORES EM SP DA SERRA DO MAR", "Lojas dos Santos e das Flores em Sp da Serra do Mar"),
    ("BRADESCO DO 15,43", "Bradesco do 15,43"), ("", ""), ("123", "123"), ("Petrobras PN", "Petrobras PN"),
])
def test_pretty_name(name, esperado):
    assert db.pretty_name(name) == esperado
    assert db.pretty_name(esperado) == esperado  # idempotente


def test_nome_exibido_sai_legivel_e_o_cru_fica_no_banco(conn):
    db.replace_catalog_market(conn, "B3", [("SANB11", "BCO SANTANDER (BRASIL) S.A.", "Ação"),
                                           ("BOVA11", "BOVA11", "ETF"), ("ABCD3", "ABCD3", "Ação")])
    db.replace_catalog_market(conn, "CRYPTO", [("BNB", "BNB", "Cripto"), ("XRP", "XRP", "Cripto")])
    db.set_index_members(conn, "IBRA", "B3", ["SANB11"])
    assert db.catalog_entry(conn, "SANB11", "B3")["name"] == "Bco Santander (Brasil) S.A."
    assert db.index_members(conn, "IBRA")[0]["name"] == "Bco Santander (Brasil) S.A."
    assert db.search_catalog(conn, "santander")[0]["name"] == "Bco Santander (Brasil) S.A."
    assert db.catalog_entry(conn, "BOVA11", "B3")["name"] == "BOVA11"
    assert db.catalog_entry(conn, "BNB", "CRYPTO")["name"] == "BNB"  # nome igual ao código fica como está
    assert next(c for c in db.all_catalog(conn) if c["symbol"] == "SANB11")["name"] == "BCO SANTANDER (BRASIL) S.A."
    db.set_alias(conn, "BOVA11", "B3", "ISHARES IBOVESPA CLASSE DE ÍNDICE - RESPONSABILIDADE LIMITADA")
    assert db.catalog_entry(conn, "BOVA11", "B3")["name"] == "Ishares Ibovespa Classe de Índice"
