"""
Testes de unidade para church/permissions.py.
Cobre IsMembroAtivo, IsAdminIgreja e IsFinanceiroIgreja.
"""
import pytest
from unittest.mock import MagicMock
from rest_framework.test import APIRequestFactory

from church.models import Membro, NivelAcesso, Pessoa, StatusMembro
from church.permissions import (
    IsAdminIgreja,
    IsFinanceiroIgreja,
    IsMembroAtivo,
)

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


def _request(user=None):
    req = factory.get("/")
    req.user = user or MagicMock(is_authenticated=False)
    return req


def _user_autenticado(make_user, email="perm@test.com", nivel=NivelAcesso.USUARIO):
    user = make_user(email=email, nome="Perm User", password="SenhaForte123!", nivel_acesso=nivel)
    return user


# ── IsMembroAtivo ─────────────────────────────────────────────────────────────


def test_ismembro_ativo_nega_anonimo(make_user):
    req = _request()
    assert not IsMembroAtivo().has_permission(req, None)


def test_ismembro_ativo_nega_sem_membro(make_user):
    user = _user_autenticado(make_user, "nomembro@test.com")
    req = _request(user)
    assert not IsMembroAtivo().has_permission(req, None)


def test_ismembro_ativo_permite_membro_ativo(make_user):
    user = _user_autenticado(make_user, "ativo@test.com")
    pessoa = Pessoa.objects.create(tipo="membro", nome="Ativo", email=user.email)
    Membro.objects.create(pessoa=pessoa, status=StatusMembro.ATIVO)
    req = _request(user)
    assert IsMembroAtivo().has_permission(req, None)


def test_ismembro_ativo_nega_membro_inativo(make_user):
    user = _user_autenticado(make_user, "inativo.perm@test.com")
    pessoa = Pessoa.objects.create(tipo="membro", nome="Inativo", email=user.email)
    Membro.objects.create(pessoa=pessoa, status=StatusMembro.INATIVO)
    req = _request(user)
    assert not IsMembroAtivo().has_permission(req, None)


# ── IsAdminIgreja ─────────────────────────────────────────────────────────────


def test_isadmin_nega_anonimo():
    req = _request()
    assert not IsAdminIgreja().has_permission(req, None)


def test_isadmin_nega_usuario_comum(make_user):
    user = _user_autenticado(make_user, "comum.adm@test.com", NivelAcesso.USUARIO)
    req = _request(user)
    assert not IsAdminIgreja().has_permission(req, None)


@pytest.mark.parametrize("nivel", [
    NivelAcesso.ADMIN,
    NivelAcesso.PASTOR,
    NivelAcesso.LIDER,
    NivelAcesso.SECRETARIA,
    NivelAcesso.FINANCEIRO,
])
def test_isadmin_permite_roles_administrativos(make_user, nivel):
    user = _user_autenticado(make_user, f"{nivel}.adm@test.com", nivel)
    req = _request(user)
    assert IsAdminIgreja().has_permission(req, None)


# ── IsFinanceiroIgreja ────────────────────────────────────────────────────────


def test_isfinanceiro_nega_anonimo():
    req = _request()
    assert not IsFinanceiroIgreja().has_permission(req, None)


def test_isfinanceiro_nega_lider(make_user):
    user = _user_autenticado(make_user, "lider.fin@test.com", NivelAcesso.LIDER)
    req = _request(user)
    assert not IsFinanceiroIgreja().has_permission(req, None)


@pytest.mark.parametrize("nivel", [
    NivelAcesso.ADMIN,
    NivelAcesso.PASTOR,
    NivelAcesso.FINANCEIRO,
])
def test_isfinanceiro_permite_roles_financeiros(make_user, nivel):
    user = _user_autenticado(make_user, f"{nivel}.fin@test.com", nivel)
    req = _request(user)
    assert IsFinanceiroIgreja().has_permission(req, None)
