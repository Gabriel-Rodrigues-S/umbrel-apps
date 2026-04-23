from typing import Any, Callable

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse
from _pytest.monkeypatch import MonkeyPatch


pytestmark = pytest.mark.django_db


MakeUserFactory = Callable[..., Any]


@pytest.mark.critico
@pytest.mark.integracao
def test_usuario_basico_recebe_403_no_financeiro(
    client: Client, make_user: MakeUserFactory
) -> None:
    usuario = make_user(email="basico_fin@example.com", nome="Basico Fin", nivel_acesso="usuario")
    client.force_login(usuario)

    response = client.get(reverse("financeiro_lancamentos"))

    assert response.status_code == 403


@pytest.mark.critico
@pytest.mark.integracao
def test_usuario_basico_recebe_403_em_membros(
    client: Client, make_user: MakeUserFactory
) -> None:
    usuario = make_user(email="basico_membros@example.com", nome="Basico Membros", nivel_acesso="usuario")
    client.force_login(usuario)

    response = client.get(reverse("membros_listar"))

    assert response.status_code == 403


@pytest.mark.critico
@pytest.mark.integracao
def test_usuario_financeiro_acessa_financeiro(
    client: Client, make_user: MakeUserFactory
) -> None:
    usuario = make_user(
        email="financeiro_ok@example.com",
        nome="Financeiro",
        nivel_acesso="financeiro",
    )
    client.force_login(usuario)

    response = client.get(reverse("financeiro_lancamentos"))

    assert response.status_code == 200


@pytest.mark.critico
@pytest.mark.integracao
def test_bootstrap_falha_sem_senha_em_ambiente(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_EMAIL", raising=False)

    with pytest.raises(CommandError):
        call_command("bootstrap_sys_edah")
