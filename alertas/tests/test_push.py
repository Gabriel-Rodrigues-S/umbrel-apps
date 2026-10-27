import base64
import json
import stat

import pytest
from pywebpush import WebPushException

from alertas import push
from alertas.banco import inscricoes, salvar_inscricao
from alertas.push import chaves, enviar_todos, texto


def sub(n):
    return {"endpoint": f"https://push.exemplo/{n}", "keys": {"p256dh": "p", "auth": "a"}}


class Resposta:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = "corpo"
        self.headers = {}


class WebpushFalso:
    """Simula pywebpush.webpush: status por endpoint."""

    def __init__(self, status=None):
        self.status = status or {}
        self.chamadas = []

    def __call__(self, subscription_info, data, vapid_private_key, vapid_claims, ttl, timeout):
        self.chamadas.append({"endpoint": subscription_info["endpoint"], "data": data,
                              "claims": dict(vapid_claims), "ttl": ttl})
        st = self.status.get(subscription_info["endpoint"], 201)
        if st == "erro":
            raise RuntimeError("falha de rede")
        if st > 202:
            raise WebPushException("falhou", response=Resposta(st))
        return Resposta(st)


# --- teste do brief ---

def test_push_nunca_leva_conteudo():
    assert texto("grave") == "Novo alerta grave no servidor"
    assert texto("normal") == "Novo alerta no servidor" and texto("info") is None


# --- extras ---

def test_chaves_geradas_uma_vez_com_modo_600(tmp_path):
    c1 = chaves(tmp_path / "config")
    arq = tmp_path / "config" / "vapid.json"
    assert stat.S_IMODE(arq.stat().st_mode) == 0o600
    c2 = chaves(tmp_path / "config")
    assert c1 == c2
    pub = base64.urlsafe_b64decode(c1["publica"] + "==")
    assert len(pub) == 65 and pub[0] == 4  # ponto não comprimido
    assert "=" not in c1["publica"]


def test_chaves_arquivo_ruim_nao_e_sobrescrito(tmp_path):
    (tmp_path / "config").mkdir()
    arq = tmp_path / "config" / "vapid.json"
    arq.write_text("{ruim")
    with pytest.raises(ValueError):
        chaves(tmp_path / "config")
    assert arq.read_text() == "{ruim"


def test_envia_texto_generico_com_sub_https(con, tmp_path):
    salvar_inscricao(con, sub(1))
    fake = WebpushFalso()
    n = enviar_todos(con, "grave", chaves(tmp_path / "c"), host="umbrel.ts.net", webpush=fake)
    assert n == 1
    ch = fake.chamadas[0]
    assert ch["data"] == "Novo alerta grave no servidor"
    assert ch["claims"]["sub"] == "https://umbrel.ts.net"
    assert ch["ttl"] == 86400


def test_info_nao_envia(con, tmp_path):
    salvar_inscricao(con, sub(1))
    fake = WebpushFalso()
    assert enviar_todos(con, "info", chaves(tmp_path / "c"), host="h.ts.net", webpush=fake) == 0
    assert fake.chamadas == []


def test_sem_host_nao_envia(con, tmp_path):
    salvar_inscricao(con, sub(1))
    fake = WebpushFalso()
    assert enviar_todos(con, "grave", chaves(tmp_path / "c"), host=None, webpush=fake) == 0
    assert fake.chamadas == []


def test_remove_inscricao_410_e_404_mantem_outras(con, tmp_path):
    for i in range(4):
        salvar_inscricao(con, sub(i))
    fake = WebpushFalso({"https://push.exemplo/0": 410, "https://push.exemplo/1": 404,
                         "https://push.exemplo/2": 500})
    n = enviar_todos(con, "normal", chaves(tmp_path / "c"), host="h.ts.net", webpush=fake)
    assert n == 1
    assert sorted(s["endpoint"] for s in inscricoes(con)) == [
        "https://push.exemplo/2", "https://push.exemplo/3"]


def test_nunca_levanta(con, tmp_path, caplog):
    salvar_inscricao(con, sub(1))
    fake = WebpushFalso({"https://push.exemplo/1": "erro"})
    assert enviar_todos(con, "grave", chaves(tmp_path / "c"), host="h.ts.net", webpush=fake) == 0
    assert "push.exemplo" not in caplog.text  # endpoint nunca vai para o log


def test_claims_nao_vazam_entre_inscricoes(con, tmp_path):
    salvar_inscricao(con, {"endpoint": "https://a.exemplo/1", "keys": {"p256dh": "p", "auth": "a"}})
    salvar_inscricao(con, {"endpoint": "https://b.exemplo/1", "keys": {"p256dh": "p", "auth": "a"}})
    fake = WebpushFalso()
    enviar_todos(con, "grave", chaves(tmp_path / "c"), host="h.ts.net", webpush=fake)
    assert all("aud" not in c["claims"] for c in fake.chamadas)


def test_webpush_real_assina_com_a_chave(tmp_path, monkeypatch):
    """Passa pelo pywebpush de verdade até o envio HTTP (interceptado)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    cli = ec.generate_private_key(ec.SECP256R1())
    p256dh = base64.urlsafe_b64encode(cli.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).rstrip(b"=").decode()
    auth = base64.urlsafe_b64encode(b"0123456789abcdef").rstrip(b"=").decode()
    capturado = {}

    class Sessao:
        def post(self, url, data, headers, timeout):
            capturado.update(url=url, headers=headers)
            return Resposta(201)

    import pywebpush
    import requests
    monkeypatch.setattr(requests, "post", lambda url, data, headers, timeout: Sessao().post(url, data, headers, timeout))
    k = chaves(tmp_path / "c")
    push._enviar_um({"endpoint": "https://push.exemplo/x", "keys": {"p256dh": p256dh, "auth": auth}},
                    "Novo alerta no servidor", k, "h.ts.net", pywebpush.webpush)
    assert capturado["url"] == "https://push.exemplo/x"
    assert k["publica"] in capturado["headers"]["Authorization"]
    assert capturado["headers"]["ttl"] == "86400"
    json.dumps(capturado["headers"])  # só strings
