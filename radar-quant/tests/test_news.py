"""Testes das notícias (sem acesso à internet)."""
import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app import db, news
from app.config import Settings

FIX = Path(__file__).parent / "fixtures"
GOOGLE = (FIX / "news_google.xml").read_text()
YAHOO = json.loads((FIX / "news_yahoo.json").read_text())


def run(coro):
    return asyncio.run(coro)


def rss(*items):
    return '<?xml version="1.0"?><rss><channel>' + "".join(items) + "</channel></rss>"


# ---------- parse_google_rss ----------
def test_google_parse():
    items = news.parse_google_rss(GOOGLE)
    assert [i["url"] for i in items] == ["https://news.google.com/rss/articles/AAA1",
                                         "https://news.google.com/rss/articles/AAA4",
                                         "https://news.google.com/rss/articles/AAA5"]
    a = items[0]
    assert a["title"] == "Lucro & dividendos da Petrobras surpreendem"  # &amp; resolvido, sufixo removido
    assert a["source"] == "InfoMoney"
    assert a["published_at"] == "2026-10-08T12:06:22+00:00"
    assert items[2]["published_at"] is None  # data inválida


def test_google_descarta_javascript_e_sem_link():
    titles = [i["title"] for i in news.parse_google_rss(GOOGLE)]
    assert "Link malicioso" not in titles and "Notícia sem link" not in titles


def test_google_titulo_longo_cortado():
    xml = rss(f"<item><title>{'x' * 5000}</title><link>https://a.example/1</link></item>")
    assert len(news.parse_google_rss(xml)[0]["title"]) == news.MAX_TITLE


def test_google_rejeita_doctype_entity_tamanho_e_truncado():
    for bad in ('<!DOCTYPE foo [<!ENTITY x "y">]>' + rss(), rss() + "<!ENTITY a 'b'>"):
        with pytest.raises(news.NewsError):
            news.parse_google_rss(bad)
    with pytest.raises(news.NewsError):
        news.parse_google_rss("x" * (3 * 1024 * 1024))
    with pytest.raises(news.NewsError):
        news.parse_google_rss(GOOGLE[:600])


def test_url_https_sem_diferenciar_maiusculas_e_limite():
    ok = rss("<item><title>a</title><link>HTTPS://a.example/1</link></item>")
    assert len(news.parse_google_rss(ok)) == 1
    longa = rss(f"<item><title>a</title><link>https://a.example/{'p' * 2000}</link></item>")
    assert news.parse_google_rss(longa) == []
    ftp = rss("<item><title>a</title><link>ftp://a.example/1</link></item>")
    assert news.parse_google_rss(ftp) == []


def test_fonte_cortada_em_80():
    xml = rss(f"<item><title>a</title><link>https://a.example/1</link><source>{'s' * 200}</source></item>")
    assert len(news.parse_google_rss(xml)[0]["source"]) == 80


# ---------- parse_yahoo ----------
def test_yahoo_parse():
    items = news.parse_yahoo(YAHOO)
    assert len(items) == 3
    assert items[0]["source"] == "Benzinga"
    assert items[0]["published_at"] == datetime.fromtimestamp(1791519786, timezone.utc).isoformat()
    assert items[1]["title"] == "Tech stocks & the week ahead"
    assert items[2]["published_at"] is None


def test_yahoo_estrutura_inesperada():
    assert news.parse_yahoo({}) == []
    assert news.parse_yahoo({"news": "x"}) == []
    assert news.parse_yahoo({"news": [1, None, {"title": "a", "link": "javascript:x"}]}) == []
    assert news.parse_yahoo([]) == []


# ---------- merge ----------
def item(t, d=None, n=0):
    return {"title": t, "url": f"https://a.example/{t}{n}", "source": "s", "published_at": d}


def test_merge_dedup_ordena_e_corta():
    a = item("Petrobras  Sobe!", "2026-10-08T10:00:00+00:00")
    b = item("petrobras sobe", "2026-10-08T11:00:00+00:00", 1)
    c = item("Outra", None)
    d = item("Mais velha", "2026-10-01T00:00:00+00:00")
    out = news.merge([c, a, d, b])
    assert [i["title"] for i in out] == ["Petrobras  Sobe!", "Mais velha", "Outra"]
    many = [item(f"t{n}", f"2026-10-{(n % 28) + 1:02d}T00:00:00+00:00") for n in range(50)]
    assert len(news.merge(many)) == news.MAX_ITEMS


# ---------- fetch_news ----------
def handler_for(urls, google=200, yahoo=200):
    def h(req):
        urls.append(req.url)
        if req.url.host == "news.google.com":
            return httpx.Response(google, text=GOOGLE)
        return httpx.Response(yahoo, json=YAHOO)
    return h


def test_fetch_b3_so_google_pt():
    urls = []
    out = run(news.fetch_news("PETR4", "B3", "Petrobras", httpx.MockTransport(handler_for(urls))))
    assert len(urls) == 1 and urls[0].host == "news.google.com"
    p = urls[0].params
    assert p["q"] == "PETR4" and p["hl"] == "pt-BR" and p["gl"] == "BR" and p["ceid"] == "BR:pt-419"
    assert len(out) == 2  # os dois itens de mesmo título viram um


def test_fetch_us_google_e_yahoo():
    urls = []
    out = run(news.fetch_news("AAPL", "US", "Apple", httpx.MockTransport(handler_for(urls))))
    g = next(u for u in urls if u.host == "news.google.com")
    y = next(u for u in urls if u.host == "query1.finance.yahoo.com")
    assert g.params["q"] == "AAPL stock" and g.params["hl"] == "en-US" and g.params["ceid"] == "US:en"
    assert y.params["q"] == "AAPL" and y.params["newsCount"] == "10" and y.params["quotesCount"] == "0"
    assert len(out) == 5


def test_fetch_cripto_usa_nome_ou_simbolo():
    urls = []
    run(news.fetch_news("BTC", "CRYPTO", "Bitcoin", httpx.MockTransport(handler_for(urls))))
    assert urls[0].params["q"] == "Bitcoin" and urls[0].params["hl"] == "pt-BR" and len(urls) == 1
    urls.clear()
    run(news.fetch_news("BTC", "CRYPTO", "", httpx.MockTransport(handler_for(urls))))
    assert urls[0].params["q"] == "BTC"


def test_fetch_uma_fonte_falha():
    out = run(news.fetch_news("AAPL", "US", None, httpx.MockTransport(handler_for([], google=500))))
    assert len(out) == 3 and out[0]["source"] in ("Benzinga", "Reuters", "Fonte Z")


def test_fetch_todas_falham():
    with pytest.raises(news.NewsError):
        run(news.fetch_news("AAPL", "US", None, httpx.MockTransport(handler_for([], 500, 500))))


def test_fetch_corpo_invalido_conta_como_falha():
    t = httpx.MockTransport(lambda r: httpx.Response(200, text="<!DOCTYPE x>"))
    with pytest.raises(news.NewsError):
        run(news.fetch_news("PETR4", "B3", None, t))


# ---------- get_news ----------
@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "radar.db")


def settings(tmp_path, provider="live"):
    return Settings(data_dir=tmp_path, provider=provider, refresh_hours=6)


def test_synthetic_news():
    a = news.synthetic_news("PETR4")
    assert len(a) == 3 and a == news.synthetic_news("PETR4")
    assert a[0]["url"] == "https://example.com/noticia/PETR4/1"


def test_get_news_sintetico(conn, tmp_path):
    aid = db.add_asset(conn, "PETR4", "B3")
    out = run(news.get_news(conn, db.get_asset(conn, aid), settings(tmp_path, "synthetic")))
    assert len(out["items"]) == 3 and out["stale"] is False and out["fetched_at"]
    assert len(db.load_news(conn, aid)[0]) == 3


def test_get_news_cache_ttl(conn, tmp_path):
    aid = db.add_asset(conn, "PETR4", "B3")
    asset = db.get_asset(conn, aid)
    calls = []
    t = httpx.MockTransport(handler_for(calls))
    first = run(news.get_news(conn, asset, settings(tmp_path), t))
    assert len(calls) == 1 and first["stale"] is False and len(first["items"]) == 2
    second = run(news.get_news(conn, asset, settings(tmp_path), t))
    assert len(calls) == 1 and second["stale"] is False and second["items"] == first["items"]


def test_get_news_cache_vencido_busca_de_novo(conn, tmp_path):
    aid = db.add_asset(conn, "PETR4", "B3")
    asset = db.get_asset(conn, aid)
    calls = []
    t = httpx.MockTransport(handler_for(calls))
    run(news.get_news(conn, asset, settings(tmp_path), t))
    old = (datetime.now(timezone.utc) - timedelta(seconds=news.TTL_SECONDS + 60)).isoformat()
    db.set_meta(conn, db._news_key(aid), old)
    run(news.get_news(conn, asset, settings(tmp_path), t))
    assert len(calls) == 2


def test_get_news_vencido_e_fonte_fora_devolve_antigo_stale(conn, tmp_path):
    aid = db.add_asset(conn, "PETR4", "B3")
    asset = db.get_asset(conn, aid)
    run(news.get_news(conn, asset, settings(tmp_path), httpx.MockTransport(handler_for([]))))
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.set_meta(conn, db._news_key(aid), old)
    out = run(news.get_news(conn, asset, settings(tmp_path), httpx.MockTransport(handler_for([], 500))))
    assert out["stale"] is True and len(out["items"]) == 2 and out["fetched_at"] == old


def test_get_news_sem_cache_e_fonte_fora(conn, tmp_path):
    aid = db.add_asset(conn, "PETR4", "B3")
    out = run(news.get_news(conn, db.get_asset(conn, aid), settings(tmp_path),
                            httpx.MockTransport(handler_for([], 500))))
    assert out["items"] == [] and out["stale"] is True and out["fetched_at"] is None


# ---------- rodada de correção 1 ----------
def test_data_fora_do_intervalo_ou_no_futuro_vira_none():
    for d in ("Fri, 31 Dec 9999 23:59:59 -0500", "Fri, 31 Dec 2999 23:59:59 GMT"):
        xml = rss(f"<item><title>a</title><link>https://a.example/1</link><pubDate>{d}</pubDate></item>")
        assert news.parse_google_rss(xml)[0]["published_at"] is None
    y = {"news": [{"title": "a", "link": "https://a.example/1", "providerPublishTime": 32503680000}]}
    assert news.parse_yahoo(y)[0]["published_at"] is None


def test_json_profundo_do_yahoo_nao_escapa():
    def h(req):
        if req.url.host == "news.google.com":
            return httpx.Response(200, text=GOOGLE)
        return httpx.Response(200, content=b"[" * 100000)
    out = run(news.fetch_news("AAPL", "US", None, httpx.MockTransport(h)))
    assert len(out) == 2  # só o Google


def test_get_news_captura_qualquer_excecao(conn, tmp_path, monkeypatch):
    aid = db.add_asset(conn, "PETR4", "B3")

    async def boom(*a, **k):
        raise RuntimeError("inesperado")
    monkeypatch.setattr(news, "fetch_news", boom)
    out = run(news.get_news(conn, db.get_asset(conn, aid), settings(tmp_path)))
    assert out["items"] == [] and out["stale"] is True


def test_url_invalida():
    for u in ("https://", "https://a b", "https://a.example/\x7fx", "http:///x", "https://[::1"):
        xml = rss(f"<item><title>a</title><link>{u}</link></item>")
        assert news.parse_google_rss(xml) == [], u


def test_remove_controle_e_direcao():
    xml = rss("<item><title>ab‮cd​ef\x7fg</title><link>https://a.example/1</link>"
              "<source>fo‮o</source></item>")
    it = news.parse_google_rss(xml)[0]
    assert it["title"] == "abcdefg" and it["source"] == "foo"


def test_corpo_grande_via_transporte():
    t = httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * (news.MAX_BODY + 1)))
    with pytest.raises(news.NewsError):
        run(news.fetch_news("PETR4", "B3", None, t))


def test_dedup_titulo_so_pontuacao():
    out = news.merge([item("!!!", "2026-10-01T00:00:00+00:00"), item("???", "2026-10-02T00:00:00+00:00", 1),
                      item("!!!", "2026-10-03T00:00:00+00:00", 2)])
    assert len(out) == 2


def test_doctype_minusculo():
    with pytest.raises(news.NewsError):
        news.parse_google_rss('<!doctype x>' + rss())


def test_simbolo_especial_codificado():
    urls = []
    run(news.fetch_news("A&B=1#x", "US", None, httpx.MockTransport(handler_for(urls))))
    g = next(u for u in urls if u.host == "news.google.com")
    assert g.params["q"] == "A&B=1#x stock" and "A%26B%3D1%23x" in str(g)
    assert next(u for u in urls if u.host != "news.google.com").params["q"] == "A&B=1#x"


def test_busca_vazia_nao_apaga_cache_bom(conn, tmp_path):
    aid = db.add_asset(conn, "PETR4", "B3")
    asset = db.get_asset(conn, aid)
    run(news.get_news(conn, asset, settings(tmp_path), httpx.MockTransport(handler_for([]))))
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.set_meta(conn, db._news_key(aid), old)
    vazio = httpx.MockTransport(lambda r: httpx.Response(200, text=rss()))
    out = run(news.get_news(conn, asset, settings(tmp_path), vazio))
    assert out["stale"] is True and len(out["items"]) == 2 and out["fetched_at"] == old
    assert len(db.load_news(conn, aid)[0]) == 2
