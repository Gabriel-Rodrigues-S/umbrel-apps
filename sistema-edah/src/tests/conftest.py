import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Limpa o cache entre testes para não acumular contadores de rate limit."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True, scope="session")
def disconnect_tenant_signals():
    """
    Remove o signal handler do django_tenants que falha sem TENANT_MODEL.
    O handler é registrado na importação de django_tenants.signals (via
    church.tenants.utils/_get_plano_features), mas não funciona no ambiente
    de testes sem TENANT_MODEL configurado.
    """
    try:
        from django.db.models.signals import post_delete
        from django_tenants.signals import tenant_delete_callback
        post_delete.disconnect(tenant_delete_callback)
    except Exception:
        pass


@pytest.fixture
def make_user(db):
    user_model = get_user_model()

    def factory(**overrides):
        defaults = {
            "email": "user@example.com",
            "nome": "Usuario Teste",
            "password": "SenhaForte123!",
        }
        defaults.update(overrides)
        password = defaults.pop("password")
        return user_model.objects.create_user(password=password, **defaults)

    return factory


@pytest.fixture
def logged_client(client, make_user):
    user = make_user(email="auth@example.com", nome="Auth")
    client.force_login(user)
    return client, user
