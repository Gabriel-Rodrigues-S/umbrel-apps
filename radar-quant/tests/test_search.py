"""Testes da busca por nome: índice em memória e reforço on-line (sem acesso à internet)."""
import asyncio
import json
import time

import httpx
import pytest

from app import db, search
from app.config import Settings

# Imita o catálogo real, com as linhas que atrapalhavam a ordenação (direitos, recibos americanos, homônimos).
_BRADESCO, _ITAU, _PETRO = "BCO BRADESCO S.A.", "ITAU UNIBANCO HOLDING S.A.", "PETROLEO BRASILEIRO S.A. PETROBRAS"
B3 = [("ABCB4", "BCO ABC BRASIL S.A.", "Ação"), ("BBAS3", "BCO BRASIL S.A.", "Ação"),
      ("SANB11", "BCO SANTANDER (BRASIL) S.A.", "Ação"), ("BBDC1", "BRADESCO DO 15,43", "Ação"),
      ("BBDC3", _BRADESCO, "Ação"), ("BBDC4", _BRADESCO, "Ação"),
      ("ITUB3", _ITAU, "Ação"), ("ITUB4", _ITAU, "Ação"),
      ("ITSA4", "ITAUSA S.A.", "Ação"), ("PETR4", _PETRO, "Ação"), ("PETR3", _PETRO, "Ação"),
      ("MGLU3", "MAGAZINE LUIZA S.A.", "Ação"), ("VALE3", "VALE S.A.", "Ação"), ("BOVA11", "BOVA11", "ETF"),
      ("PRIO3", "PETRO RIO S.A.", "Ação"), ("RPMG3", "REFINARIA DE PETROLEOS MANGUINHOS S.A.", "Ação")]
US = [("VALE", "Vale S.A. American Depositary Shares", "Ação"), ("AAPL", "Apple Inc.", "Ação"),
      ("APLE", "Apple Hospitality REIT", "Ação"),
      ("BSBR", "Banco Santander Brasil SA American Depositary Shares", "Ação"),
      ("BIXI", "Bitcoin Infrastructure Acquisition Corp", "Ação"),
      ("BIXIU", "Bitcoin Infrastructure Acquisition Corp", "Ação"),
      ("BIXIW", "Bitcoin Infrastructure Acquisition Corp", "Ação"),
      ("PBR", "Petroleo Brasileiro S.A. Petrobras ADS", "Ação"),
      ("PBR.A", "Petroleo Brasileiro S.A. Petrobras ADS", "Ação")]
CRYPTO = [("BTC", "Bitcoin", "Cripto"), ("BCH", "Bitcoin Cash", "Cripto")]
TOTAL = len(B3) + len(US) + len(CRYPTO)
IBOV = ["BBAS3", "BBDC4", "ITUB4", "ITSA4", "PETR4", "PETR3", "MGLU3", "VALE3"]
IBRA = IBOV + ["ABCB4", "BBDC3", "ITUB3", "SANB11"]


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
    db.replace_catalog_market(c, "CRYPTO", CRYPTO)
    db.set_index_members(c, "IBOV", "B3", IBOV)
    db.set_index_members(c, "IBRA", "B3", IBRA)
    db.set_index_members(c, "SP500", "US", ["AAPL"])
    db.set_alias(c, "BBAS3", "B3", "Banco do Brasil S.A.")
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
    assert syms(search.search_local(conn, "banco do brasil")) == ["BBAS3", "ABCB4", "SANB11", "BSBR"]
    assert syms(search.search_local(conn, "brasil banco"))[0] == "BBAS3"
    assert syms(search.search_local(conn, "bco brasil"))[0] == "BBAS3"  # quem digita a abreviação continua achando
    assert syms(search.search_local(conn, "magaz luiza")) == ["MGLU3"]
    assert syms(search.search_local(conn, "Magazine Luiza S.A.")) == ["MGLU3"]  # palavras vazias não bloqueiam


def test_local_formato_do_resultado(conn):
    assert search.search_local(conn, "banco do brasil")[0] == {
        "symbol": "BBAS3", "market": "B3", "name": "Banco do Brasil S.A.", "kind": "Ação",
        "indices": ["IBOV", "IBRA"]}


@pytest.mark.parametrize("q", ["itau", "itaú", "ITAÚ"])
def test_local_itau(conn, q):
    # ITUB4 (IBOV e IBRA) antes de ITUB3 (só IBRA); em ITSA4 "itau" é só prefixo de "itausa" (meia cobertura):
    # empata com ITUB3 em pontos e cobertura e fica na frente pela ordem alfabética
    assert syms(search.search_local(conn, q)) == ["ITUB4", "ITSA4", "ITUB3"]


@pytest.mark.parametrize("q", ["BBAS3", "bbas3", "bbas3.sa", " BBAS3 "])
def test_local_codigo(conn, q):
    assert syms(search.search_local(conn, q)) == ["BBAS3"]


def test_local_prefixo_de_codigo_antes_de_nome(conn):
    assert syms(search.search_local(conn, "petr")) == ["PETR4", "PETR3", "PBR", "PBR.A", "PRIO3", "RPMG3"]
    assert syms(search.search_local(conn, "petroleo")) == ["PETR4", "PETR3", "PBR", "PBR.A", "RPMG3"]
    assert syms(search.search_local(conn, "bbdc")) == ["BBDC4", "BBDC3", "BBDC1"]


def test_local_apple_e_vale(conn):
    assert syms(search.search_local(conn, "apple")) == ["AAPL", "APLE"]
    vale = search.search_local(conn, "vale")
    assert [(r["symbol"], r["market"]) for r in vale[:2]] == [("VALE", "US"), ("VALE3", "B3")]


@pytest.mark.parametrize("q", ["%", "_", "'", '"', "'; DROP TABLE catalog;--", "a" * 64, "   ", "", "\\", "%%__"])
def test_local_entradas_hostis(conn, q):
    r = search.search_local(conn, q)
    assert isinstance(r, list) and len(r) < TOTAL
    assert db.catalog_count(conn) == TOTAL


def test_local_so_palavras_vazias_usa_como_estao(conn):
    assert len(search.search_local(conn, "s a", limit=25)) == 18  # todo papel com "S.A." no nome
    assert syms(search.search_local(conn, "de")) == ["RPMG3", "VALE", "BSBR"]  # "de" e "depositary"
    assert syms(search.search_local(conn, "petroleo de s.a.")) == syms(search.search_local(conn, "petroleo"))


def test_local_limite(conn):
    assert len(search.search_local(conn, "s", limit=3)) == 3
    assert len(search.search_local(conn, "s")) == 12 and len(search.search_local(conn, "s", limit=25)) == 18
    assert syms(search.search_local(conn, "s", limit=1)) == syms(search.search_local(conn, "s"))[:1]


def test_local_alias_passa_a_ser_encontrado(conn, monkeypatch):
    monkeypatch.setattr(search, "ABBR", {})  # sem a expansão, só o alias leva ao papel
    db.set_alias(conn, "BBAS3", "B3", "")  # como na 1.1.0: ainda sem nome aprendido
    search.invalidate()
    assert syms(search.search_local(conn, "banco do brasil")) == ["BSBR"]  # o único com "Banco" por extenso
    assert search.search_local(conn, "ishares") == []
    db.set_alias(conn, "BBAS3", "B3", "Banco do Brasil S.A.")
    db.set_alias(conn, "BOVA11", "B3", "iShares Ibovespa Fundo de Índice")
    assert syms(search.search_local(conn, "banco do brasil")) == ["BSBR"]  # índice em memória ainda é o antigo
    search.invalidate()
    assert search.search_local(conn, "banco do brasil")[0] == {
        "symbol": "BBAS3", "market": "B3", "name": "Banco do Brasil S.A.", "kind": "Ação",
        "indices": ["IBOV", "IBRA"]}
    assert syms(search.search_local(conn, "ishares indice")) == ["BOVA11"]
    assert syms(search.search_local(conn, "bco brasil"))[0] == "BBAS3"  # o nome cru continua valendo


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
        assert syms(search.search_local(c, "banco do brasil"))[0] == "BBAS3"
    assert (time.perf_counter() - t) / 20 < 0.03


# ---------- ordenação no catálogo real (casos que saíam errados) ----------

def test_ordem_banco_do_brasil(conn):
    # cobertura do nome: "Banco do Brasil" (1,0) passa "Bco ABC Brasil" e "Bco Santander (Brasil)" (0,67)
    assert syms(search.search_local(conn, "banco do brasil"))[0] == "BBAS3"
    assert syms(search.search_local(conn, "BBAS3")) == ["BBAS3"]  # símbolo exato continua em 1º


def test_ordem_bitcoin(conn):
    assert syms(search.search_local(conn, "bitcoin")) == ["BTC", "BCH", "BIXI", "BIXIU", "BIXIW"]


def test_ordem_bradesco_direitos_por_ultimo(conn):
    assert syms(search.search_local(conn, "bradesco")) == ["BBDC4", "BBDC3", "BBDC1"]
    assert syms(search.search_local(conn, "bbdc1")) == ["BBDC1"]  # código inteiro digitado: sem penalidade


def test_ordem_itau_e_petrobras(conn):
    itau = syms(search.search_local(conn, "itau"))
    assert itau[0] == "ITUB4" and itau.index("ITUB4") < itau.index("ITUB3")
    assert syms(search.search_local(conn, "petrobras")) == ["PETR4", "PETR3", "PBR", "PBR.A"]  # B3 antes dos ADRs


def test_penalidade_de_direitos_so_nos_sufixos_1_2_9_10(conn):
    penalizados = {e[0] for e in search._index(conn)[0] if e[6]}
    assert penalizados == {"BBDC1"}  # BOVA11, a unit SANB11 e as ações 3/4 ficam de fora
    db.replace_catalog_market(conn, "B3", [(s, "X S.A.", "Ação") for s in (
        "PETR1", "PETR2", "PETR9", "PETR10", "PETR3", "PETR4", "PETR5", "PETR6", "PETR7", "PETR8", "PETR11",
        "BOVA11", "SANB11", "PETR12", "ABCDE1", "PETR34")])
    db.replace_catalog_market(conn, "US", [("ABCD1", "X Inc.", "Ação")])  # só vale para a B3
    search.invalidate()
    assert {e[0] for e in search._index(conn)[0] if e[6]} == {"PETR1", "PETR2", "PETR9", "PETR10"}
    pontos = {r[2]["symbol"]: r[0] for r in search._rank(conn, "x")}
    assert pontos["PETR5"] - pontos["PETR1"] == 250 and pontos["BOVA11"] == pontos["PETR11"] == pontos["PETR5"]


def test_bonus_por_indice_e_por_mercado(conn):
    pontos = {r[2]["symbol"]: r[0] for r in search._rank(conn, "banco")}
    assert pontos["BBDC4"] - pontos["BBDC3"] == 40  # IBOV + IBRA contra só IBRA
    bitcoin = {r[2]["symbol"]: r for r in search._rank(conn, "bitcoin")}
    assert bitcoin["BTC"][1] == 1.0 and bitcoin["BCH"][1] == 0.5 and bitcoin["BIXI"][1] == pytest.approx(1 / 3)
    assert bitcoin["BTC"][0] == 300 + 80 + 40 + 150 + 30  # nome, 1ª palavra, igualdade, cobertura, cripto


def test_desempate_por_cobertura(conn):
    db.replace_catalog_market(conn, "US", [("AAA", "Zeta Alfa Beta", "Ação"), ("AAB", "Zeta", "ETF"),
                                           ("AAC", "Zeta Inc", "ETF")])
    db.set_index_members(conn, "SP500", "US", ["AAA"])
    search.invalidate()
    # AAA: 420 + 50 (cobertura 1/3) + 40 (índice) + 20 (ação) = 530; AAB e AAC: 420 + 150 = 570
    assert syms(search.search_local(conn, "zeta")) == ["AAB", "AAC", "AAA"]


# ---------- search_remote ----------

QUOTES = [
    {"symbol": "BBAS3.SA", "exchange": "SAO", "longname": "Banco do Brasil S.A.", "shortname": "BRASIL ON NM",
     "quoteType": "EQUITY"},
    {"symbol": "PETR4F.SA", "exchange": "SAO", "longname": "Petróleo Brasileiro S.A. - Petrobras"},
    {"symbol": "BBAS.BA", "exchange": "BUE", "longname": "Banco do Brasil BA"},
    {"symbol": "BZLA.F", "exchange": "FRA", "longname": "Banco do Brasil F"},
    {"symbol": "BDORY", "exchange": "PNK", "longname": "Banco do Brasil ADR"},
    {"symbol": "ITUB", "exchange": "NYQ", "shortname": "Itau  Unibanco\tBanco\x00 Holding SA"},
    {"symbol": "BRK-B", "exchange": "NYQ", "longname": "Berkshire Hathaway Inc.", "quoteType": ["EQUITY"]},
    {"symbol": "AAPL", "exchange": "NMS", "longname": "A" * 200, "quoteType": "ETF"},
    {"symbol": 123, "exchange": "NMS"},
    "lixo",
]  # 10 itens: é o teto do que se lê de uma resposta


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
        {"symbol": "BBAS3", "market": "B3", "name": "Banco do Brasil S.A.", "kind": "Ação"},
        {"symbol": "ITUB", "market": "US", "name": "Itau Unibanco Banco Holding SA", "kind": None},
        {"symbol": "BRK.B", "market": "US", "name": "Berkshire Hathaway Inc.", "kind": None},
        {"symbol": "AAPL", "market": "US", "name": "A" * 80, "kind": "ETF"}]
    for lixo in ({"symbol": "BDORY2", "exchange": "OID"}, {"symbol": "BBAS3.SA", "exchange": "FRA"},
                 {"symbol": "abc", "exchange": "NYQ"}, {"symbol": "TOOLONG", "exchange": "NMS"},
                 {"symbol": "PETR4F.SA", "exchange": "SAO"}, {"symbol": "X.SA", "exchange": "SAO"}):
        assert search._map(lixo) is None
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
        search.clear_remote_cache()  # fecha o disjuntor que a falha anterior abriu
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


def test_remote_falha_nao_fica_em_cache(monkeypatch):
    agora, calls = [1000.0], []
    monkeypatch.setattr(search, "_now", lambda: agora[0])
    assert run(search.search_remote("itau", transport(calls=calls, status=500))) == []
    agora[0] += search.BREAKER_SECONDS + 1  # passado o disjuntor, a mesma consulta volta à rede
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
    db.set_alias(conn, "BOVA11", "B3", "Nome já aprendido")
    search.invalidate()
    calls = []
    quotes = [eq("BOVA11.SA", "iShares Ibovespa Fundo de Índice", kind="ETF")]
    out = run(search.search(conn, "ishares", 12, settings(tmp_path), transport(quotes, calls=calls)))
    assert [(r["symbol"], r["name"]) for r in out] == [("BOVA11", "Nome já aprendido")] and len(calls) == 1


def test_search_insere_papel_fora_do_catalogo(conn, tmp_path):
    quotes = [eq("WEGE3.SA", "WEG S.A."),
              {"symbol": "MSFT", "exchange": "NMS", "shortname": "Microsoft Corporation", "quoteType": "EQUITY"}]
    out = run(search.search(conn, "weg", 12, settings(tmp_path), transport(quotes)))
    assert out == [{"symbol": "MSFT", "market": "US", "name": "Microsoft Corporation", "kind": "Ação", "indices": []},
                   {"symbol": "WEGE3", "market": "B3", "name": "WEG S.A.", "kind": "Ação", "indices": []}]
    assert db.catalog_entry(conn, "WEGE3", "B3")["name"] == "WEG S.A."
    assert syms(search.search_local(conn, "wege3")) == ["WEGE3"]


BRADESCO = [
    {"symbol": "BBDC4.SA", "exchange": "SAO", "longname": "Banco Bradesco S.A.", "quoteType": "EQUITY"},
    {"symbol": "BBD", "exchange": "NYQ", "longname": "Banco Bradesco S.A. ADR", "quoteType": "EQUITY"}]


def test_search_ordem_e_duplicatas(conn, tmp_path):
    # BBDC4 já vem do local (467,5 pontos): não duplica e fica acima do acerto só remoto (450); limit corta no fim
    out = run(search.search(conn, "bradesc", 12, settings(tmp_path), transport(BRADESCO)))
    assert [(r["symbol"], r["market"]) for r in out] == [("BBDC4", "B3"), ("BBD", "US"), ("BBDC3", "B3"),
                                                         ("BBDC1", "B3")]
    assert out[0]["name"] == "Banco Bradesco S.A."  # o nome recém-aprendido já aparece
    search.clear_remote_cache()
    assert len(run(search.search(conn, "bradesc", 2, settings(tmp_path), transport(BRADESCO)))) == 2


def test_search_sintetico_nunca_chama_o_transporte(conn, tmp_path):
    calls = []
    out = run(search.search(conn, "banco do brasil", 12, settings(tmp_path, "synthetic"), transport(calls=calls)))
    assert syms(out)[0] == "BBAS3" and calls == []


@pytest.mark.parametrize("q", ["BBAS3", "bbas3", "bbas3.sa", "vale", "BBDC1"])
def test_search_simbolo_exato_nao_vai_a_rede(conn, tmp_path, q):
    calls = []
    out = run(search.search(conn, q, 12, settings(tmp_path), transport(calls=calls)))
    assert out[0]["symbol"] == q.upper().removesuffix(".SA") and calls == []


def test_search_remoto_fora_do_ar_devolve_os_locais(conn, tmp_path):
    calls = []
    out = run(search.search(conn, "bradesc", 12, settings(tmp_path), transport(calls=calls, status=500)))
    assert syms(out) == ["BBDC4", "BBDC3", "BBDC1"] and len(calls) == 1
    assert run(search.search(conn, "", 12, settings(tmp_path), transport(status=500))) == []


# ---------- rodada final: rede só quando o catálogo não resolve; teto e saneamento; nomes legíveis ----------

def eq(symbol, name, exchange="SAO", kind="EQUITY"):
    return {"symbol": symbol, "exchange": exchange, "longname": name, "quoteType": kind}


def clock(monkeypatch, start=1000.0):
    agora = [start]
    monkeypatch.setattr(search, "_now", lambda: agora[0])
    return agora


def test_reforco_so_quando_o_local_e_fraco(conn, tmp_path, caplog):
    db.upsert_catalog_entry(conn, "WEGE3", "B3", "WEG S.A.", "Ação")
    db.set_alias(conn, "PETR4", "B3", "Petrobras")
    search.invalidate()
    calls, live = [], settings(tmp_path)
    t = transport([], calls=calls)
    for q in ("petrobras",  # nome coberto por inteiro
              "apple", "weg",  # idem ("weg" também é prefixo de WEGE3)
              "PETR", "petr", "bbd", "itu",  # faixa de prefixo de símbolo
              "itau",  # 625 pontos: já está na faixa de cima
              "bbas3", "btc",  # símbolo exato com dígito / de cripto
              "brasil", "santander", "banco brasil"):  # palavras inteiras do nome
        assert run(search.search(conn, q, 12, live, t)), q
        assert calls == [], q
    with caplog.at_level("INFO", logger="radar.search"):
        assert run(search.search(conn, "inexistente", 12, live, t)) == []  # lista local vazia é fraca
        assert syms(run(search.search(conn, "bradesc", 12, live, t))) == ["BBDC4", "BBDC3", "BBDC1"]  # parciais
        assert syms(run(search.search(conn, "petrob", 12, live, t)))[0] == "PETR4"  # palavra pela metade
    assert [c.url.params["q"] for c in calls] == ["inexistente", "bradesc", "petrob"]
    infos = [r.getMessage() for r in caplog.records if r.name == "radar.search" and r.levelname == "INFO"]
    assert len(infos) == 3 and "'bradesc'" in infos[1] and "0 acerto" in infos[1]


def test_simbolo_exato_dos_eua_sem_digito_nao_suprime_o_reforco(conn, tmp_path):
    db.upsert_catalog_entry(conn, "ZETA", "US", "ZetaPower International PLC", "Ação")
    search.invalidate()
    calls, live = [], settings(tmp_path)
    t = transport([eq("ZETA3.SA", "Zeta Brasil S.A.")], calls=calls)
    out = run(search.search(conn, "zeta", 12, live, t))
    assert [(r["symbol"], r["name"]) for r in out] == [("ZETA", "ZetaPower International PLC"),
                                                       ("ZETA3", "Zeta Brasil S.A.")]
    assert len(calls) == 1
    assert syms(run(search.search(conn, "zeta3", 12, live, t))) == ["ZETA3"] and len(calls) == 1  # tem dígito


def test_disjuntor_depois_de_falha_e_de_429(monkeypatch):
    agora, calls = clock(monkeypatch), []
    ok = transport([eq("BBAS3.SA", "Banco do Brasil S.A.")], calls=calls)
    assert run(search.search_remote("consulta um", transport(calls=calls, status=503))) == []
    assert run(search.search_remote("consulta dois", ok)) == [] and len(calls) == 1  # 60 s sem rede
    agora[0] += 59
    assert run(search.search_remote("consulta dois", ok)) == [] and len(calls) == 1
    agora[0] += 2
    assert syms(run(search.search_remote("consulta dois", ok))) == ["BBAS3"] and len(calls) == 2
    assert run(search.search_remote("consulta tres", transport(calls=calls, status=429))) == []
    agora[0] += 14 * 60
    assert run(search.search_remote("consulta quatro", ok)) == [] and len(calls) == 3  # 15 min sem rede
    agora[0] += 61
    assert syms(run(search.search_remote("consulta quatro", ok))) == ["BBAS3"] and len(calls) == 4


def test_disjuntor_tambem_em_falha_de_rede_e_nao_em_resposta_vazia(monkeypatch):
    clock(monkeypatch)
    calls = []

    def caiu(request):
        calls.append(request)
        raise httpx.ConnectError("fora do ar", request=request)

    vazio = transport([], calls=calls)
    assert run(search.search_remote("nada aqui", vazio)) == []
    assert run(search.search_remote("nada aqui", vazio)) == [] and len(calls) == 1  # vazio legítimo: cache
    assert run(search.search_remote("outra coisa", httpx.MockTransport(caiu))) == [] and len(calls) == 2
    assert run(search.search_remote("mais uma", vazio)) == [] and len(calls) == 2  # disjuntor aberto


def test_busca_interativa_tem_teto_de_tempo(conn, tmp_path, monkeypatch):
    assert search.SEARCH_TIMEOUT == 2 and search.TIMEOUT == 4

    async def lento(request):
        await asyncio.sleep(30)
        return httpx.Response(200, json={"quotes": []})

    monkeypatch.setattr(search, "SEARCH_TIMEOUT", 0.05)
    t0 = time.perf_counter()
    out = run(search.search(conn, "bradesc", 12, settings(tmp_path), httpx.MockTransport(lento)))
    assert syms(out) == ["BBDC4", "BBDC3", "BBDC1"] and time.perf_counter() - t0 < 1  # devolve o que o catálogo tem


def test_consultas_identicas_em_voo_compartilham_a_requisicao():
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"quotes": [eq("BBAS3.SA", "Banco do Brasil S.A.")]})

    async def tres():
        t = httpx.MockTransport(handler)
        return await asyncio.gather(search.search_remote("banco do brasil", t),
                                    search.search_remote(" Banco do  Brasil", t),
                                    search.search_remote("banco do brasil", t))

    a, b, c = run(tres())
    assert len(calls) == 1 and syms(a) == syms(b) == syms(c) == ["BBAS3"]
    assert a is not b and a[0] is not b[0]  # cada chamador recebe a sua cópia


def test_teto_de_itens_e_de_insercoes(conn, tmp_path):
    antes = db.catalog_count(conn)
    quotes = [eq(f"NOVA{i}.SA", f"Empresa Nova {i} S.A.") for i in range(3, 9)] * 3  # 18 itens, 6 símbolos
    quotes = quotes[:9] + [eq("ZETA3.SA", "Zeta S.A.")] + [eq("FORA3.SA", "Fora dos dez primeiros S.A.")]
    hits = run(search.search_remote("empresa nova", transport(quotes)))
    assert syms(hits) == ["NOVA3", "NOVA4", "NOVA5", "NOVA6", "NOVA7", "NOVA8", "ZETA3"]  # só os 10 primeiros itens
    out = run(search.search(conn, "empresa nova", 12, settings(tmp_path), transport(quotes)))
    assert syms(out) == ["NOVA4", "NOVA3", "NOVA5"] and db.catalog_count(conn) == antes + 3  # 3 inserções


def test_so_insere_acao_ou_etf_com_nome(conn, tmp_path):
    quotes = [{"symbol": "SEMN3.SA", "exchange": "SAO", "quoteType": "EQUITY"},  # sem nome
              eq("FUND3.SA", "Fundo Mútuo", kind="MUTUALFUND"), eq("OPCA3.SA", "Opção", kind="OPTION"),
              {"symbol": "SEMT3.SA", "exchange": "SAO", "longname": "Sem tipo S.A."},
              eq("IVVB11.SA", "iShares S&P 500 FIC FI", kind="ETF"), eq("XYZ", "Xyz Corp", "NYQ")]
    antes = db.catalog_count(conn)
    out = run(search.search(conn, "termo novo", 12, settings(tmp_path), transport(quotes)))
    assert out == [{"symbol": "XYZ", "market": "US", "name": "Xyz Corp", "kind": "Ação", "indices": []},
                   {"symbol": "IVVB11", "market": "B3", "name": "iShares S&P 500 FIC FI", "kind": "ETF",
                    "indices": []}]
    assert db.catalog_count(conn) == antes + 2


def test_clean_name_descarta_substitutos_e_uso_privado():
    assert search.clean_name("Banco\ud800 do Brasil￿ S.A.\udfff") == "Banco do Brasil S.A."
    search.clean_name("\ud800x\ud800").encode("utf-8")  # sempre codificável


def test_nome_com_substituto_solitario_nao_derruba_a_busca(conn, tmp_path):
    body = json.dumps({"quotes": [eq("BOVA11.SA", "iShares \ud800Ibovespa"), eq("NOVO3.SA", "Novo\udc00 S.A.")]})
    assert "\\ud800" in body
    out = run(search.search(conn, "ishares", 12, settings(tmp_path), transport(body=body.encode())))
    assert [(r["symbol"], r["name"]) for r in out] == [("BOVA11", "iShares Ibovespa"), ("NOVO3", "Novo S.A.")]
    assert [h["name"] for h in run(search.search_remote("ishares"))] == ["iShares Ibovespa", "Novo S.A."]  # cache
    assert db.catalog_entry(conn, "BOVA11", "B3")["name"] == "iShares Ibovespa"


def test_falha_ao_gravar_nao_derruba_a_busca(conn, tmp_path, monkeypatch, caplog):
    def boom(*a, **k):
        raise UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed")

    monkeypatch.setattr(db, "set_alias", boom)
    monkeypatch.setattr(db, "upsert_catalog_entry", boom)
    with caplog.at_level("ERROR", logger="radar.search"):
        out = run(search.search(conn, "bradesc", 12, settings(tmp_path), transport(BRADESCO)))
    assert [(r["symbol"], r["market"]) for r in out] == [("BBDC4", "B3"), ("BBD", "US"), ("BBDC3", "B3"),
                                                         ("BBDC1", "B3")]
    assert out[1] == {"symbol": "BBD", "market": "US", "name": "Banco Bradesco S.A. ADR", "kind": "Ação",
                      "indices": []}
    assert any(r.name == "radar.search" and r.exc_info for r in caplog.records)
    assert db.catalog_entry(conn, "BBD", "US") is None and out[0]["name"] == "BCO Bradesco S.A."  # alias não gravou


def test_cobertura_zero_quando_o_nome_e_o_proprio_codigo(conn):
    db.replace_catalog_market(conn, "B3", [("GOLL4", "GOL LINHAS AEREAS INTELIGENTES S.A.", "Ação"),
                                           ("GOLB11", "GOLB11", "FII"), ("GOLD11", "GOLD11", "ETF"),
                                           ("VISA34", "VISA34", "BDR")])
    db.replace_catalog_market(conn, "US", [("V", "Visa Inc.", "Ação")])
    db.set_index_members(conn, "SP500", "US", ["V"])
    search.invalidate()
    assert syms(search.search_local(conn, "gol")) == ["GOLL4", "GOLB11", "GOLD11"]
    assert syms(search.search_local(conn, "visa")) == ["V", "VISA34"]
    assert {r[2]["symbol"]: r[1] for r in search._rank(conn, "gol")}["GOLB11"] == 0


def test_nomes_em_maiusculas_saem_legiveis(conn, tmp_path):
    por = {r["symbol"]: r["name"] for r in search.search_local(conn, "banco", limit=25)}
    assert por["SANB11"] == "BCO Santander (Brasil) S.A." and por["ABCB4"] == "BCO ABC Brasil S.A."
    assert por["BBAS3"] == "Banco do Brasil S.A." and por["BSBR"].startswith("Banco Santander Brasil SA American")
    assert search.search_local(conn, "bova")[0]["name"] == "BOVA11"  # nome igual ao código fica como está
    assert syms(search.search_local(conn, "BCO SANTANDER")) == syms(search.search_local(conn, "bco santander"))
    quotes = [eq("BOVA11.SA", "ISHARES IBOVESPA CLASSE DE ÍNDICE - RESPONSABILIDADE LIMITADA", kind="ETF")]
    out = run(search.search(conn, "ishares", 12, settings(tmp_path), transport(quotes)))
    assert out[0]["name"] == "Ishares Ibovespa Classe de Índice"
    assert next(c for c in db.all_catalog(conn) if c["symbol"] == "BOVA11")["alias"] == out[0]["name"]  # gravado assim


def test_desempate_entre_classes_da_mesma_empresa(conn):
    assert syms(search.search_local(conn, "petr"))[:2] == ["PETR4", "PETR3"]
    assert syms(search.search_local(conn, "petrobras"))[:2] == ["PETR4", "PETR3"]
    db.replace_catalog_market(conn, "B3", [(s, "CIA XIS S.A.", "Ação") for s in (
        "XISA5", "XISA11", "XISA3", "XISA4", "XISA6", "AAAA5", "ZZZZ4")])
    search.invalidate()
    assert syms(search.search_local(conn, "cia")) == ["AAAA5", "XISA4", "XISA3", "XISA11", "XISA5", "XISA6", "ZZZZ4"]
    assert syms(search.search_local(conn, "xis"))[:5] == ["XISA4", "XISA3", "XISA11", "XISA5", "XISA6"]


def test_invalidate_nao_espera_reconstrucao_em_curso(conn):
    import threading
    assert syms(search.search_local(conn, "bova")) == ["BOVA11"]
    with search._lock:  # como se outra thread estivesse reconstruindo o índice
        th = threading.Thread(target=search.invalidate, daemon=True)
        th.start()
        th.join(1)
        travou = th.is_alive()
    th.join(1)
    assert not travou
    db.set_alias(conn, "BOVA11", "B3", "iShares Ibovespa")  # e a invalidação feita durante a obra vale
    assert search.search_local(conn, "ishares") and search.search_local(conn, "ishares")[0]["symbol"] == "BOVA11"


# ---------- último ajuste: duas fases, local forte por palavra inteira, apelidos de marca ----------

def test_remote_false_nunca_toca_a_rede(conn, tmp_path):
    calls = []
    t = transport([eq("NOVO3.SA", "Novo S.A.")], calls=calls)
    assert run(search.search(conn, "inexistente", 12, settings(tmp_path), t, remote=False)) == []
    assert run(search.search_detail(conn, "inexistente", 12, settings(tmp_path), t, remote=False)) == ([], False)
    assert calls == [] and db.catalog_entry(conn, "NOVO3", "B3") is None  # nem aprende nada
    out, usou = run(search.search_detail(conn, "inexistente", 12, settings(tmp_path), t))
    assert syms(out) == ["NOVO3"] and usou is True and len(calls) == 1
    out, usou = run(search.search_detail(conn, "inexistente", 12, settings(tmp_path), t))
    assert syms(out) == ["NOVO3"] and usou is True and len(calls) == 1  # servida do cache remoto também conta
    assert run(search.search_detail(conn, "bbas3", 12, settings(tmp_path), t))[1] is False  # local forte
    assert run(search.search_detail(conn, "inexistente", 12, settings(tmp_path, "synthetic"), t))[1] is False


def test_detail_nao_conta_como_remoto_com_disjuntor_aberto(conn, tmp_path):
    assert run(search.search_detail(conn, "termo um", 12, settings(tmp_path), transport(status=503))) == ([], True)
    calls = []
    assert run(search.search_detail(conn, "termo dois", 12, settings(tmp_path), transport(calls=calls))) == ([], False)
    assert calls == []


def test_local_forte_quando_toda_palavra_da_consulta_e_palavra_do_nome(conn, tmp_path):
    db.set_alias(conn, "PETR4", "B3", "Petróleo Brasileiro S.A. - Petrobras")
    db.upsert_catalog_entry(conn, "ABEV3", "B3", "AMBEV S.A.", "Ação")
    search.invalidate()
    calls, live = [], settings(tmp_path)
    t = transport([], calls=calls)
    for q in ("petrobras", "ambev", "banco brasil", "brasil", "petróleo brasileiro", "bradesco", "luiza"):
        assert run(search.search(conn, q, 12, live, t)), q
        assert calls == [], q
    for n, q in enumerate(("petrob", "bradesc", "magaz", "luiz"), 1):  # palavra pela metade: fraco
        assert run(search.search(conn, q, 12, live, t)), q
        assert len(calls) == n, q


NICK_B3 = [("VIVT3", "TELEF BRASIL S.A.", "Ação"), ("ROXO34", "ROXO34", "BDR"), ("AAPL34", "AAPL34", "BDR"),
           ("MGLU3", "MAGAZINE LUIZA S.A.", "Ação"), ("BBAS3", "BCO BRASIL S.A.", "Ação"),
           ("BBSE3", "BB SEGURIDADE PARTICIPACOES S.A.", "Ação"), ("NATU3", "NATURA S.A.", "Ação")]
NICK_US = [("NU", "Nu Holdings Ltd.", "Ação"), ("AAPL", "Apple Inc.", "Ação"),
           ("APLE", "Apple Hospitality REIT", "Ação")]


@pytest.fixture
def marcas(tmp_path):
    c = db.connect(tmp_path / "marcas.db")
    db.replace_catalog_market(c, "B3", NICK_B3)
    db.replace_catalog_market(c, "US", NICK_US)
    db.set_index_members(c, "SP500", "US", ["AAPL"])
    return c


def test_apelidos_de_marca(marcas, tmp_path):
    calls, live = [], settings(tmp_path)
    t = transport([], calls=calls)
    achou = lambda q: syms(run(search.search(marcas, q, 12, live, t)))
    assert achou("vivo") == ["VIVT3"] and achou("Vivo") == ["VIVT3"]
    assert achou("magalu") == ["MGLU3"] and achou("magal") == ["MGLU3"]  # prefixo com 5+ letras ainda sugere
    assert achou("nubank") == ["ROXO34", "NU"] and achou("nuban") == ["ROXO34", "NU"]  # ordem de preferência
    assert achou("bb") == ["BBAS3", "BBSE3"]  # o apelido passa o prefixo de símbolo de BBSE3
    assert achou("natura") == ["NATU3"]
    assert achou("apple") == ["AAPL", "AAPL34", "APLE"]  # o papel americano continua em 1º; o BDR só entra
    assert calls == []  # apelido que casa é resultado forte
    assert achou("nuba") == [] and achou("mag") == ["MGLU3"]  # menos de 5 letras: só o que a busca normal acha
    assert search.search_local(marcas, "nu")[0]["symbol"] == "NU"
    assert search._rank(marcas, "vivo")[0][0] == 1050 and search._rank(marcas, "nubank")[1][0] == 1049
    assert [r[0] for r in search._rank(marcas, "nuban")] == [500, 499]  # prefixo: junta-se à lista, sem ir ao topo
    assert {r[2]["symbol"]: r[0] for r in search._rank(marcas, "apple")}["AAPL34"] == 500


def test_apelido_depende_do_que_existe_no_catalogo(marcas, tmp_path):
    calls, live = [], settings(tmp_path)
    t = transport([], calls=calls)
    db.replace_catalog_market(marcas, "B3", [r for r in NICK_B3 if r[0] != "ROXO34"])
    search.invalidate()
    assert syms(run(search.search(marcas, "nubank", 12, live, t))) == ["NU"] and calls == []
    db.replace_catalog_market(marcas, "US", [r for r in NICK_US if r[0] != "NU"])
    search.invalidate()
    assert run(search.search(marcas, "nubank", 12, live, t)) == [] and len(calls) == 1  # nenhum existe: vai à rede


def test_apelido_exato_passa_simbolo_exato(marcas, tmp_path):
    db.upsert_catalog_entry(marcas, "VIVO", "US", "VivoPower International PLC", "Ação")
    db.upsert_catalog_entry(marcas, "BB", "US", "BlackBerry Limited", "Ação")
    db.set_index_members(marcas, "SP500", "US", ["AAPL", "VIVO", "BB"])  # nem o bônus de índice passa o apelido
    search.invalidate()
    calls = []
    achou = lambda q: syms(run(search.search(marcas, q, 12, settings(tmp_path), transport([], calls=calls))))
    assert achou("vivo") == ["VIVT3", "VIVO"]  # o dono é brasileiro: Vivo é a Telefônica Brasil
    assert achou("bb") == ["BBAS3", "BB", "BBSE3"]
    assert achou("vivt3") == ["VIVT3"] and achou("vivo3") == []  # código inteiro continua sendo código
    assert len(calls) == 1 and calls[0].url.params["q"] == "vivo3"  # só o que não resolve vai à rede
    pontos = {r[2]["symbol"]: r[0] for r in search._rank(marcas, "vivo")}
    assert pontos["VIVO"] > 1050 and pontos["VIVT3"] == pontos["VIVO"] + 50


def test_prefixo_de_apelido_nao_pega_carona(tmp_path):
    c = db.connect(tmp_path / "carona.db")
    db.replace_catalog_market(c, "B3", [
        ("PSSA3", "PORTO SEGURO S.A.", "Ação"), ("PTBL3", "PORTOBELLO S.A.", "Ação"),
        ("RDOR3", "REDE D OR SAO LUIZ S.A.", "Ação"), ("INBR32", "INBR32", "BDR"), ("MELI34", "MELI34", "BDR"),
        ("SANB11", "BCO SANTANDER (BRASIL) S.A.", "Ação"), ("SANT3", "SANTOS BRASIL S.A.", "Ação"),
        ("MGLU3", "MAGAZINE LUIZA S.A.", "Ação"), ("MAGA3", "MAGA3", "Ação"), ("MAGAL3", "MAGAL3", "Ação"),
        ("CMIG4", "CIA ENERGETICA DE MINAS GERAIS", "Ação")])
    db.replace_catalog_market(c, "US", [("INTC", "Intel Corporation", "Ação"), ("MAGAL", "Magal Inc.", "Ação")])
    assert syms(search.search_local(c, "port")) == ["PTBL3", "PSSA3"]  # por nome, não por apelido
    assert search._rank(c, "port")[0][0] < 600 and search._rank(c, "rede")[0][0] < 600
    assert syms(search.search_local(c, "inte")) == ["INTC"] and syms(search.search_local(c, "merc")) == []
    assert syms(search.search_local(c, "sant")) == ["SANT3", "SANB11"]  # prefixo de símbolo e nome; sem apelido
    assert syms(search.search_local(c, "santa")) == ["SANB11"] and search._rank(c, "santa")[0][0] == 500
    assert syms(search.search_local(c, "mercado l")) == []  # apelido de duas palavras só vale inteiro
    assert syms(search.search_local(c, "mercado livre")) == ["MELI34"]
    assert syms(search.search_local(c, "cemi")) == [] and syms(search.search_local(c, "cemig")) == ["CMIG4"]
    # "magal" sugere MGLU3 (500) sem passar o símbolo exato MAGAL nem o prefixo de símbolo MAGAL3
    assert syms(search.search_local(c, "magal")) == ["MAGAL", "MAGAL3", "MGLU3"]
    assert syms(search.search_local(c, "magalu")) == ["MGLU3"]


def test_tabela_de_apelidos_conferida(tmp_path):
    assert len(search.NICKNAMES) == 52
    for nick, (boost, papers) in search.NICKNAMES.items():
        assert nick == " ".join(search._words(nick)) and boost in (1050, 500) and papers
        assert all(m in ("B3", "US") and s == s.upper() for s, m in papers)
    assert {n for n, (b, _) in search.NICKNAMES.items() if b == 500} == {
        "apple", "microsoft", "tesla", "nvidia", "amazon", "google", "facebook", "meta"}
    assert search.NICKNAMES["nubank"] == (1050, (("ROXO34", "B3"), ("NU", "US")))
    todos = {p for _, papers in search.NICKNAMES.values() for p in papers}
    assert not {("OIBR3", "B3"), ("NTCO3", "B3"), ("CPLE6", "B3"), ("AZUL4", "B3")} & todos  # saíram da B3
    c = db.connect(tmp_path / "apelidos.db")
    db.replace_catalog_market(c, "B3", [("AXIA3", "AXIA ENERGIA S.A.", "Ação"),
                                        ("MBRF3", "MBRF GLOBAL FOODS", "Ação"),
                                        ("UGPA3", "ULTRAPAR PARTICIPACOES S.A.", "Ação")])
    for q, esperado in (("eletrobras", ["AXIA3"]), ("sadia", ["MBRF3"]), ("perdigao", ["MBRF3"]), ("brf", ["MBRF3"]),
                        ("Perdigão", ["MBRF3"]), ("ipiranga", ["UGPA3"]), ("ultrapar", ["UGPA3"]),
                        ("embraer", []), ("vivo", []), ("meta", [])):  # papel fora do catálogo: ignorado
        assert syms(search.search_local(c, q)) == esperado, q


def test_disjuntor_nao_abre_com_corpo_ruim_mas_ha_cache_negativo(monkeypatch):
    agora, calls = clock(monkeypatch), []
    ok = transport([eq("BBAS3.SA", "Banco do Brasil S.A.")], calls=calls)
    for i, ruim in enumerate([transport(calls=calls, body=b"<html>"), transport(calls=calls, body=b'{"quotes": 1}'),
                              transport(calls=calls, body=b" " * 2_000_000), transport(calls=calls, status=404)]):
        assert run(search.search_remote(f"consulta {i}", ruim)) == []
    assert len(calls) == 4  # nenhuma dessas abriu o disjuntor
    assert syms(run(search.search_remote("outra consulta", ok))) == ["BBAS3"] and len(calls) == 5
    assert run(search.search_remote("consulta 0", ok)) == [] and len(calls) == 5  # cache negativo de 10 min
    agora[0] += 601
    assert syms(run(search.search_remote("consulta 0", ok))) == ["BBAS3"] and len(calls) == 6
    assert search.NEGATIVE_SECONDS == 600
