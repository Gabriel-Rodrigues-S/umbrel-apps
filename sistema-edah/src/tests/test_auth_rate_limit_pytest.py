import pytest
from django.core.cache import cache
from django.urls import reverse


pytestmark = pytest.mark.django_db


@pytest.mark.critico
@pytest.mark.integracao
def test_login_retorna_429_apos_excesso_tentativas(client, make_user, monkeypatch):
    cache.clear()
    make_user(email="limit_login@example.com", nome="Limit Login", password="SenhaForte123!")

    monkeypatch.setattr("church.views_app.auth.RATE_LIMIT_LOGIN_TENTATIVAS", 1)

    response_1 = client.post(
        reverse("login"),
        data={"username": "limit_login@example.com", "password": "senha-invalida"},
    )
    response_2 = client.post(
        reverse("login"),
        data={"username": "limit_login@example.com", "password": "senha-invalida"},
    )

    assert response_1.status_code == 200
    assert response_2.status_code == 429
    assert "Retry-After" in response_2


@pytest.mark.critico
@pytest.mark.integracao
def test_login_sucesso_reseta_rate_limit(client, make_user, monkeypatch):
    cache.clear()
    make_user(email="reset_login@example.com", nome="Reset Login", password="SenhaForte123!")

    monkeypatch.setattr("church.views_app.auth.RATE_LIMIT_LOGIN_TENTATIVAS", 2)

    response_invalido = client.post(
        reverse("login"),
        data={"username": "reset_login@example.com", "password": "senha-invalida"},
    )
    response_sucesso = client.post(
        reverse("login"),
        data={"username": "reset_login@example.com", "password": "SenhaForte123!"},
        follow=False,
    )
    client.logout()
    response_apos_reset = client.post(
        reverse("login"),
        data={"username": "reset_login@example.com", "password": "senha-invalida"},
    )

    assert response_invalido.status_code == 200
    assert response_sucesso.status_code == 302
    assert response_apos_reset.status_code == 200
