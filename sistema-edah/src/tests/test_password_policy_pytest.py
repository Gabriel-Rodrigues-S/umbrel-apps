import pytest

from church.forms import UserCreateForm, UserPasswordForm


pytestmark = pytest.mark.django_db


@pytest.mark.critico
def test_user_password_form_rejeita_senha_fraca(make_user):
    user = make_user(email="senha_fraca_form@example.com", nome="Senha Fraca", password="SenhaForte123!")
    form = UserPasswordForm(
        user,
        data={
            "senha_atual": "SenhaForte123!",
            "nova_senha": "123",
            "confirmar": "123",
        },
    )

    assert form.is_valid() is False
    assert "nova_senha" in form.errors


@pytest.mark.critico
def test_user_create_form_rejeita_senha_fraca():
    form = UserCreateForm(
        data={
            "nome": "Novo Usuario",
            "email": "novo_usuario@example.com",
            "nivel_acesso": "usuario",
            "status": "ativo",
            "is_staff": False,
            "is_active": True,
            "password": "123",
        }
    )

    assert form.is_valid() is False
    assert "password" in form.errors