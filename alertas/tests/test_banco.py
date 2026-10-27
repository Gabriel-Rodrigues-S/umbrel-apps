import os
import time

from alertas.banco import (abrir, inscricoes, inserir, inserir_se_ausente, limpar_antigos,
                           listar, marcar_lido, remover_inscricao, salvar_inscricao)
from conftest import inserir_em


# --- testes do brief ---

def test_graves_nao_lidos_primeiro(con):
    inserir(con, "gateway", "normal", "n", ""); g = inserir(con, "historico", "grave", "g", "")
    assert listar(con)[0]["id"] == g


def test_retencao_365_dias(con):
    inserir_em(con, dias_atras=366); inserir_em(con, dias_atras=10)
    assert limpar_antigos(con) == 1


# --- extras ---

def test_ordem_completa(con):
    g_lido = inserir(con, "historico", "grave", "g1", "")
    n1 = inserir(con, "gateway", "normal", "n1", "")
    g = inserir(con, "historico", "grave", "g2", "")
    n2 = inserir(con, "gateway", "info", "n2", "")
    assert marcar_lido(con, g_lido) is True
    # grave não lido primeiro; depois os demais do mais novo ao mais antigo
    assert [a["id"] for a in listar(con)] == [g, n2, n1, g_lido]


def test_campos_e_data_local(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Manaus")
    time.tzset()
    try:
        i = inserir(con, "gateway", "normal", "título", "detalhe", criado_em=0)
        a = listar(con)[0]
        assert a == {"id": i, "origem": "gateway", "gravidade": "normal", "titulo": "título",
                     "detalhes": "detalhe", "criado_em": "1969-12-31T20:00:00-04:00", "lido": False}
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_marcar_lido_inexistente(con):
    assert marcar_lido(con, 999) is False


def test_inserir_se_ausente_respeita_janela(con):
    a = inserir_se_ausente(con, "alertas", "normal", "Remetente desconhecido", "x", janela_s=600)
    b = inserir_se_ausente(con, "alertas", "normal", "Remetente desconhecido", "x", janela_s=600)
    assert a is not None and b is None
    assert len(listar(con)) == 1


def test_wal_e_arquivo_criado(tmp_path):
    c = abrir(tmp_path / "sub" / "alertas.db")
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert os.path.exists(tmp_path / "sub" / "alertas.db")
    c.close()


def test_inscricoes_upsert_e_remocao(con):
    s = {"endpoint": "https://push.exemplo/a", "keys": {"p256dh": "p", "auth": "a"}}
    salvar_inscricao(con, s)
    salvar_inscricao(con, {**s, "keys": {"p256dh": "p2", "auth": "a2"}})
    assert inscricoes(con) == [{"endpoint": "https://push.exemplo/a",
                                "keys": {"p256dh": "p2", "auth": "a2"}}]
    remover_inscricao(con, "https://push.exemplo/a")
    assert inscricoes(con) == []
