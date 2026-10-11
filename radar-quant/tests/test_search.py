"""Testes da busca por nome: índice em memória e reforço on-line (sem acesso à internet)."""
import asyncio
import json
import time

import httpx
import pytest

from app import db, search
from app.config import Settings

B3 = [("BBAS3", "BCO BRASIL S.A.", "Ação"), ("ITUB4", "ITAU UNIBANCO HOLDING S.A.", "Ação"),
      ("ITSA4", "ITAUSA S.A.", "Ação"), ("PETR4", "PETROLEO BRASILEIRO S.A. PETROBRAS", "Ação"),
      ("PETR3", "PETROLEO BRASILEIRO S.A. PETROBRAS", "Ação"), ("MGLU3", "MAGAZINE LUIZA S.A.", "Ação"),
      ("VALE3", "VALE S.A.", "Ação"), ("BOVA11", "BOVA11", "ETF"), ("PRIO3", "PETRO RIO S.A.", "Ação"),
      ("RPMG3", "REFINARIA DE PETROLEOS MANGUINHOS S.A.", "Ação")]
US = [("VALE", "Vale S.A. American Depositary Shares", "Ação"), ("AAPL", "Apple Inc.", "Ação"),
      ("APLE", "Apple Hospitality REIT", "Ação")]


def run(coro):
    return asyncio.run(coro)


def settings(tmp_path, provider="live"):
    return Settings(data_dir=tmp_path, provider=provider, refresh_hours=6)


@pytest.fixture(autouse=True)
def limpa():
    search.invalidate()
    search.clear_remote_cache()
    yield
    search.invalidate()
    search.clear_remote_cache()


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "radar.db")
    db.replace_catalog_market(c, "B3", B3)
    db.replace_catalog_market(c, "US", US)
    db.set_index_members(c, "IBOV", "B3", ["BBAS3", "ITUB4", "ITSA4", "PETR4", "PETR3", "MGLU3", "VALE3"])
    db.set_index_members(c, "SP500", "US", ["AAPL"])
    return c


def syms(rows):
    return [r["symbol"] for r in rows]


# ---------- normalize ----------

def test_normalize():
    assert search.normalize("Itaú Unibanco") == ["itau", "unibanco"]
    bb = search.normalize("BCO BRASIL S.A.")
    assert {"bco", "banco", "brasil"} <= set(bb) and bb[0] == "bco"
    assert search.normalize("  São-Paulo/Ações, (Petróleo)!  ") == ["sao", "paulo", "acoes", "petroleo"]
    assert search.normalize("CIA ENERG MINAS") == ["cia", "companhia", "energ", "energia", "minas"]
    assert search.normalize("") == [] and search.normalize("%_'\"") == []


# ---------- search_local ----------

def test_local_nome_da_empresa(conn):
    assert syms(search.search_local(conn, "banco do brasil"))[0] == "BBAS3"
    assert syms(search.search_local(conn, "brasil banco")) == ["BBAS3"]
    assert syms(search.search_local(conn, "bco brasil")) == ["BBAS3"]  # quem digita a abreviação continua achando
    assert syms(search.search_local(conn, "magaz luiza")) == ["MGLU3"]
    assert syms(search.search_local(conn, "Magazine Luiza S.A.")) == ["MGLU3"]  # palavras vazias não bloqueiam


def test_local_formato_do_resultado(conn):
    assert search.search_local(conn, "banco do brasil")[0] == {
        "symbol": "BBAS3", "market": "B3", "name": "BCO BRASIL S.A.", "kind": "Ação", "indices": ["IBOV"]}


@pytest.mark.parametrize("q", ["itau", "itaú", "ITAÚ"])
def test_local_itau(conn, q):
    # ITUB4 soma +40 (o token "itau" casa por igualdade); em ITSA4 "itau" é só prefixo de "itausa"
    assert syms(search.search_local(conn, q)) == ["ITUB4", "ITSA4"]


@pytest.mark.parametrize("q", ["BBAS3", "bbas3", "bbas3.sa", " BBAS3 "])
def test_local_codigo(conn, q):
    assert syms(search.search_local(conn, q)) == ["BBAS3"]


def test_local_prefixo_de_codigo_antes_de_nome(conn):
    assert syms(search.search_local(conn, "petr")) == ["PETR3", "PETR4", "PRIO3", "RPMG3"]
    assert syms(search.search_local(conn, "petroleo")) == ["PETR3", "PETR4", "RPMG3"]


def test_local_apple_e_vale(conn):
    assert syms(search.search_local(conn, "apple")) == ["AAPL", "APLE"]
    vale = search.search_local(conn, "vale")
    assert [(r["symbol"], r["market"]) for r in vale[:2]] == [("VALE", "US"), ("VALE3", "B3")]


@pytest.mark.parametrize("q", ["%", "_", "'", '"', "'; DROP TABLE catalog;--", "a" * 64, "   ", "", "\\", "%%__"])
def test_local_entradas_hostis(conn, q):
    r = search.search_local(conn, q)
    assert isinstance(r, list) and len(r) < 13
    assert db.catalog_count(conn) == 13


def test_local_so_palavras_vazias_usa_como_estao(conn):
    assert len(search.search_local(conn, "s a")) == 10  # todo papel com "S.A." no nome
    assert syms(search.search_local(conn, "de")) == ["RPMG3", "VALE"]  # "de" e "depositary"
    assert syms(search.search_local(conn, "petroleo de s.a.")) == ["PETR3", "PETR4", "RPMG3"]  # ignoradas


def test_local_limite(conn):
    assert len(search.search_local(conn, "s", limit=3)) == 3
    assert len(search.search_local(conn, "s")) == 10
    assert syms(search.search_local(conn, "s", limit=1)) == syms(search.search_local(conn, "s"))[:1]


def test_local_alias_passa_a_ser_encontrado(conn, monkeypatch):
    monkeypatch.setattr(search, "ABBR", {})  # sem a expansão, só o alias leva ao papel
    search.invalidate()
    assert search.search_local(conn, "banco do brasil") == []
    assert search.search_local(conn, "ishares") == []
    db.set_alias(conn, "BBAS3", "B3", "Banco do Brasil S.A.")
    db.set_alias(conn, "BOVA11", "B3", "iShares Ibovespa Fundo de Índice")
    assert search.search_local(conn, "banco do brasil") == []  # índice em memória ainda é o antigo
    search.invalidate()
    assert search.search_local(conn, "banco do brasil")[0] == {
        "symbol": "BBAS3", "market": "B3", "name": "Banco do Brasil S.A.", "kind": "Ação", "indices": ["IBOV"]}
    assert syms(search.search_local(conn, "ishares indice")) == ["BOVA11"]
    assert syms(search.search_local(conn, "bco brasil")) == ["BBAS3"]  # o nome cru continua valendo


def test_local_indice_por_conexao(conn, tmp_path):
    assert search.search_local(conn, "apple")
    outro = db.connect(tmp_path / "outro.db")
    assert search.search_local(outro, "apple") == []  # outro banco não herda o índice


def test_local_rapido_com_catalogo_grande(tmp_path):
    c = db.connect(tmp_path / "grande.db")
    db.replace_catalog_market(c, "US", [(f"T{i:05d}", f"Empresa {i} Holdings Corp. Common Stock", "Ação")
                                        for i in range(14500)])
    db.replace_catalog_market(c, "B3", B3)
    search.search_local(c, "banco")  # constrói o índice
    t = time.perf_counter()
    for _ in range(20):
        assert syms(search.search_local(c, "banco do brasil")) == ["BBAS3"]
    assert (time.perf_counter() - t) / 20 < 0.03


# ---------- search_remote ----------

QUOTES = [
    {"symbol": "BBAS3.SA", "exchange": "SAO", "longname": "Banco do Brasil S.A.", "shortname": "BRASIL ON NM"},
    {"symbol": "PETR4F.SA", "exchange": "SAO", "longname": "Petróleo Brasileiro S.A. - Petrobras"},
    {"symbol": "BBAS.BA", "exchange": "BUE", "longname": "Banco do Brasil BA"},
    {"symbol": "BZLA.F", "exchange": "FRA", "longname": "Banco do Brasil F"},
    {"symbol": "BDORY", "exchange": "PNK", "longname": "Banco do Brasil ADR"},
    {"symbol": "BDORY2", "exchange": "OID", "longname": "Outro OTC"},
    {"symbol": "ITUB", "exchange": "NYQ", "shortname": "Itau  Unibanco\tBanco\x00 Holding SA"},
    {"symbol": "BRK-B", "exchange": "NYQ", "longname": "Berkshire Hathaway Inc."},
    {"symbol": "AAPL", "exchange": "NMS", "longname": "A" * 200},
    {"symbol": "BBAS3.SA", "exchange": "FRA", "longname": "bolsa errada"},
    {"symbol": "abc", "exchange": "NYQ", "longname": "minúsculo"},
    {"symbol": "TOOLONG", "exchange": "NMS", "longname": "seis letras"},
    {"symbol": 123, "exchange": "NMS"},
    "lixo",
]


def transport(quotes=QUOTES, calls=None, status=200, body=None):
    def handler(request):
        if calls is not None:
            calls.append(request)
        if body is not None:
            return httpx.Response(status, content=body)
        return httpx.Response(status, json={"quotes": quotes})
    return httpx.MockTransport(handler)


def test_remote_mapeia_e_filtra():
    calls = []
    out = run(search.search_remote("banco do brasil", transport(calls=calls)))
    assert out == [
        {"symbol": "BBAS3", "market": "B3", "name": "Banco do Brasil S.A."},
        {"symbol": "ITUB", "market": "US", "name": "Itau Unibanco Banco Holding SA"},
        {"symbol": "BRK.B", "market": "US", "name": "Berkshire Hathaway Inc."},
        {"symbol": "AAPL", "market": "US", "name": "A" * 80}]
    req = calls[0]
    assert req.url.host == "query1.finance.yahoo.com" and req.url.path == "/v1/finance/search"
    assert dict(req.url.params) == {"q": "banco do brasil", "quotesCount": "8", "newsCount": "0"}
    assert req.headers["user-agent"] == "Mozilla/5.0 (compatible; RadarQuantBot/1.0)"


def test_remote_falhas_devolvem_lista_vazia(caplog):
    def timeout(request):
        raise httpx.ReadTimeout("lento", request=request)

    def caiu(request):
        raise httpx.ConnectError("fora do ar", request=request)

    for i, t in enumerate([transport(status=500), transport(body=b"<html>"), transport(body=b'{"quotes": "x"}'),
                           transport(body=b"[1, 2]"), transport(body=b'{"quotes": [' + b" " * 2_000_000 + b"]}"),
                           transport(body=b"[" * 100_000), httpx.MockTransport(timeout),
                           httpx.MockTransport(caiu)]):
        with caplog.at_level("WARNING", logger="radar.search"):
            assert run(search.search_remote(f"consulta {i}", t)) == []
    assert len([r for r in caplog.records if r.name == "radar.search"]) == 8


def test_remote_cache_e_consulta_curta():
    calls = []
    t = transport(calls=calls)
    a = run(search.search_remote("Banco do  Brasil", t))
    assert run(search.search_remote(" banco do brasil ", t)) == a and len(calls) == 1  # mesma consulta normalizada
    assert run(search.search_remote("bb", t)) == [] and run(search.search_remote("  a ", t)) == []
    assert len(calls) == 1


def test_remote_falha_nao_fica_em_cache():
    calls = []
    assert run(search.search_remote("itau", transport(calls=calls, status=500))) == []
    assert syms(run(search.search_remote("itau", transport(calls=calls)))) == ["BBAS3", "ITUB", "BRK.B", "AAPL"]
    assert len(calls) == 2


def test_remote_cache_expira_e_tem_teto(monkeypatch):
    calls = []
    t = transport(calls=calls)
    agora = [1000.0]
    monkeypatch.setattr(search, "_now", lambda: agora[0])
    run(search.search_remote("apple", t))
    agora[0] += search.CACHE_SECONDS - 1
    run(search.search_remote("apple", t))
    assert len(calls) == 1
    agora[0] += 2
    run(search.search_remote("apple", t))
    assert len(calls) == 2
    for i in range(search.CACHE_MAX + 10):
        run(search.search_remote(f"consulta {i}", t))
    assert len(search._remote_cache) == search.CACHE_MAX


# ---------- search (local + remoto) ----------

def test_search_local_fraco_aprende_alias(conn, tmp_path):
    quotes = [{"symbol": "BOVA11.SA", "exchange": "SAO", "longname": "iShares Ibovespa Fundo de Índice"}]
    out = run(search.search(conn, "ishares ibovespa", 12, settings(tmp_path), transport(quotes)))
    assert out == [{"symbol": "BOVA11", "market": "B3", "name": "iShares Ibovespa Fundo de Índice", "kind": "ETF",
                    "indices": []}]
    assert db.missing_alias(conn, "B3", ["BOVA11"]) == []
    assert syms(search.search_local(conn, "ishares")) == ["BOVA11"]  # índice derrubado depois de aprender


def test_search_nao_troca_alias_existente(conn, tmp_path):
    db.set_alias(conn, "BBAS3", "B3", "Nome já aprendido")
    quotes = [{"symbol": "BBAS3.SA", "exchange": "SAO", "longname": "Banco do Brasil S.A."}]
    out = run(search.search(conn, "banco do brasil", 12, settings(tmp_path), transport(quotes)))
    assert [(r["symbol"], r["name"]) for r in out] == [("BBAS3", "Nome já aprendido")]


def test_search_insere_papel_fora_do_catalogo(conn, tmp_path):
    quotes = [{"symbol": "WEGE3.SA", "exchange": "SAO", "longname": "WEG S.A."},
              {"symbol": "MSFT", "exchange": "NMS", "shortname": "Microsoft Corporation"}]
    out = run(search.search(conn, "weg", 12, settings(tmp_path), transport(quotes)))
    assert out == [{"symbol": "MSFT", "market": "US", "name": "Microsoft Corporation", "kind": "Ação", "indices": []},
                   {"symbol": "WEGE3", "market": "B3", "name": "WEG S.A.", "kind": "Ação", "indices": []}]
    assert db.catalog_entry(conn, "WEGE3", "B3")["name"] == "WEG S.A."
    assert syms(search.search_local(conn, "wege3")) == ["WEGE3"]


def test_search_ordem_e_duplicatas(conn, tmp_path):
    # ITUB4 já vem do local (500 pontos): não duplica e fica acima do acerto só remoto (450); limit corta no fim
    quotes = [{"symbol": "ITUB4.SA", "exchange": "SAO", "longname": "Itaú Unibanco Holding S.A."},
              {"symbol": "ITUB", "exchange": "NYQ", "longname": "Itaú Unibanco Holding S.A. ADR"}]
    out = run(search.search(conn, "itau", 12, settings(tmp_path), transport(quotes)))
    assert [(r["symbol"], r["market"]) for r in out] == [("ITUB4", "B3"), ("ITSA4", "B3"), ("ITUB", "US")]
    assert out[0]["name"] == "Itaú Unibanco Holding S.A."  # o nome recém-aprendido já aparece
    assert len(run(search.search(conn, "itau", 2, settings(tmp_path), transport(quotes)))) == 2


def test_search_sintetico_nunca_chama_o_transporte(conn, tmp_path):
    calls = []
    out = run(search.search(conn, "banco do brasil", 12, settings(tmp_path, "synthetic"), transport(calls=calls)))
    assert syms(out) == ["BBAS3"] and calls == []


def test_search_so_vai_a_rede_quando_o_local_e_fraco(conn, tmp_path):
    calls = []
    t = transport([], calls=calls)
    assert len(run(search.search(conn, "s", 12, settings(tmp_path), t))) == 10  # 1 caractere
    assert len(run(search.search(conn, "s.a.", 12, settings(tmp_path), t))) == 10  # 5+ resultados locais
    assert calls == []
    assert syms(run(search.search(conn, "apple", 12, settings(tmp_path), t))) == ["AAPL", "APLE"]  # só 2 locais
    assert len(calls) == 1


def test_search_remoto_fora_do_ar_devolve_os_locais(conn, tmp_path):
    out = run(search.search(conn, "banco do brasil", 12, settings(tmp_path), transport(status=500)))
    assert syms(out) == ["BBAS3"]
    assert run(search.search(conn, "", 12, settings(tmp_path), transport(status=500))) == []
