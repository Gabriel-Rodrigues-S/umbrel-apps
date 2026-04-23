import json

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from church.models import Mensagem, Pessoa, Membro, StatusMembro


pytestmark = pytest.mark.django_db


@pytest.fixture
def chat_users(make_user):
    remetente = make_user(email="remetente@example.com", nome="Remetente")
    destinatario = make_user(email="destinatario@example.com", nome="Destinatario")
    return remetente, destinatario


@pytest.mark.parametrize(
    ("com", "desde"),
    [
        ("abc", "0"),
        ("1", "xyz"),
        ("-10", "0"),
        ("1", "-1"),
    ],
)
@pytest.mark.critico
@pytest.mark.integracao
def test_chat_mensagens_retorna_400_para_parametros_invalidos(client, chat_users, com, desde):
    remetente, _ = chat_users
    client.force_login(remetente)

    response = client.get(reverse("api_chat_mensagens"), {"com": com, "desde": desde})

    assert response.status_code == 400
    assert response.json()["ok"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"destinatario_id": "abc", "mensagem": "oi"},
        {"destinatario_id": 0, "mensagem": "oi"},
        {"destinatario_id": 999999, "mensagem": "oi"},
        {"destinatario_id": 1, "mensagem": ""},
        {"destinatario_id": 1, "mensagem": "a" * 2001},
    ],
)
@pytest.mark.critico
@pytest.mark.integracao
def test_chat_enviar_rejeita_payloads_invalidos(client, chat_users, payload):
    remetente, destinatario = chat_users
    client.force_login(remetente)

    data = dict(payload)
    if data.get("destinatario_id") == 1:
        data["destinatario_id"] = destinatario.id

    response = client.post(
        reverse("api_chat_enviar"),
        data=json.dumps(data),
        content_type="application/json",
    )

    assert response.status_code in {400, 404}
    assert response.json()["ok"] is False


@pytest.mark.critico
@pytest.mark.integracao
def test_chat_enviar_retorna_400_quando_autoenvio(client, chat_users):
    remetente, _ = chat_users
    client.force_login(remetente)

    response = client.post(
        reverse("api_chat_enviar"),
        data=json.dumps({"destinatario_id": remetente.id, "mensagem": "teste"}),
        content_type="application/json",
    )

    assert response.status_code == 400


@pytest.mark.critico
@pytest.mark.integracao
def test_chat_enviar_exige_csrf(chat_users):
    remetente, destinatario = chat_users
    client = Client(enforce_csrf_checks=True)
    client.force_login(remetente)

    response = client.post(
        reverse("api_chat_enviar"),
        data=json.dumps({"destinatario_id": destinatario.id, "mensagem": "Oi"}),
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.critico
@pytest.mark.integracao
def test_chat_ping_retorna_apenas_contatos_com_conversa(client, make_user):
    remetente = make_user(email="ping-rem@example.com", nome="Remetente Ping")
    contato = make_user(email="ping-contato@example.com", nome="Contato Ping")
    make_user(email="ping-fora@example.com", nome="Fora Ping")
    Mensagem.objects.create(remetente=remetente, destinatario=contato, mensagem="Ola")

    client.force_login(remetente)
    response = client.get(reverse("api_chat_ping"))

    assert response.status_code == 200
    usuarios = response.json()["usuarios"]
    ids = {u["id"] for u in usuarios}
    assert contato.id in ids
    assert len(ids) == 1


@pytest.mark.critico
@pytest.mark.integracao
def test_chat_ping_retorna_contagem_de_nao_lidas_por_remetente(client, make_user):
    destinatario = make_user(email="ping-dest@example.com", nome="Destino")
    remetente = make_user(email="ping-remetente@example.com", nome="Remetente")
    outro = make_user(email="ping-outro@example.com", nome="Outro")

    Mensagem.objects.create(remetente=remetente, destinatario=destinatario, mensagem="m1", lida=False)
    Mensagem.objects.create(remetente=remetente, destinatario=destinatario, mensagem="m2", lida=False)
    Mensagem.objects.create(remetente=outro, destinatario=destinatario, mensagem="m3", lida=False)

    client.force_login(destinatario)
    response = client.get(reverse("api_chat_ping"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["nao_lidas"][str(remetente.id)] == 2
    assert payload["nao_lidas"][str(outro.id)] == 1


@pytest.mark.critico
@pytest.mark.integracao
def test_chat_enviar_retorna_429_quando_ultrapassa_rate_limit(client, chat_users, monkeypatch):
    remetente, destinatario = chat_users
    client.force_login(remetente)
    cache.clear()
    monkeypatch.setattr("church.views_app.chat_api.RATE_LIMIT_CHAT_ENVIAR", 1)

    response_ok = client.post(
        reverse("api_chat_enviar"),
        data=json.dumps({"destinatario_id": destinatario.id, "mensagem": "primeira"}),
        content_type="application/json",
    )
    response_limited = client.post(
        reverse("api_chat_enviar"),
        data=json.dumps({"destinatario_id": destinatario.id, "mensagem": "segunda"}),
        content_type="application/json",
    )

    assert response_ok.status_code == 200
    assert response_limited.status_code == 429
    assert response_limited.json()["erro"] == "rate_limited"


@pytest.mark.integracao
def test_chat_mensagens_retorna_lista_com_sucesso(client, make_user):
    remetente = make_user(email="msgsuccess-r@x.com", nome="R")
    destinatario = make_user(email="msgsuccess-d@x.com", nome="D")
    Mensagem.objects.create(remetente=remetente, destinatario=destinatario, mensagem="Ola!")

    client.force_login(remetente)
    resp = client.get(reverse("api_chat_mensagens"), {"com": str(destinatario.id), "desde": "0"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert len(payload["mensagens"]) == 1
    assert payload["mensagens"][0]["mensagem"] == "Ola!"


@pytest.mark.integracao
def test_chat_mensagens_filtro_desde(client, make_user):
    """Parâmetro 'desde' filtra mensagens com id > desde."""
    remetente = make_user(email="desde-r@x.com", nome="R")
    destinatario = make_user(email="desde-d@x.com", nome="D")
    m1 = Mensagem.objects.create(remetente=remetente, destinatario=destinatario, mensagem="Primeira")
    m2 = Mensagem.objects.create(remetente=remetente, destinatario=destinatario, mensagem="Segunda")

    client.force_login(remetente)
    resp = client.get(reverse("api_chat_mensagens"), {"com": str(destinatario.id), "desde": str(m1.id)})

    assert resp.status_code == 200
    msgs = resp.json()["mensagens"]
    assert len(msgs) == 1
    assert msgs[0]["mensagem"] == "Segunda"
