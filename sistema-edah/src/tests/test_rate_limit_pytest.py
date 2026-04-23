import time

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import override_settings
from django.test import RequestFactory

from church.rate_limit import check_rate_limit, reset_rate_limit


pytestmark = pytest.mark.django_db


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.mark.critico
def test_check_rate_limit_bloqueia_quando_excede_limite(rf):
    cache.clear()
    request = rf.get("/qualquer", REMOTE_ADDR="10.0.0.1")
    request.user = AnonymousUser()

    limited_1, retry_1 = check_rate_limit(request, scope="teste", limit=1, window_seconds=60)
    limited_2, retry_2 = check_rate_limit(request, scope="teste", limit=1, window_seconds=60)

    assert limited_1 is False
    assert retry_1 == 0
    assert limited_2 is True
    assert retry_2 >= 1


@pytest.mark.critico
def test_reset_rate_limit_limpa_bucket(rf):
    cache.clear()
    request = rf.get("/qualquer", REMOTE_ADDR="10.0.0.2")
    request.user = AnonymousUser()

    check_rate_limit(request, scope="reset", limit=1, window_seconds=60)
    limited_before_reset, _ = check_rate_limit(request, scope="reset", limit=1, window_seconds=60)
    reset_rate_limit(request, scope="reset")
    limited_after_reset, retry_after_reset = check_rate_limit(
        request,
        scope="reset",
        limit=1,
        window_seconds=60,
    )

    assert limited_before_reset is True
    assert limited_after_reset is False
    assert retry_after_reset == 0


@pytest.mark.critico
def test_rate_limit_expira_apos_janela(rf):
    cache.clear()
    request = rf.get("/qualquer", REMOTE_ADDR="10.0.0.3")
    request.user = AnonymousUser()

    check_rate_limit(request, scope="janela", limit=1, window_seconds=1)
    limited_now, _ = check_rate_limit(request, scope="janela", limit=1, window_seconds=1)
    time.sleep(1.1)
    limited_after_window, retry_after_window = check_rate_limit(
        request,
        scope="janela",
        limit=1,
        window_seconds=1,
    )

    assert limited_now is True
    assert limited_after_window is False
    assert retry_after_window == 0


@pytest.mark.critico
def test_rate_limit_usuario_autenticado_ignora_x_forwarded_for(rf, make_user):
    cache.clear()
    user = make_user(email="auth_rate@example.com", nome="Auth Rate")

    request_1 = rf.get("/qualquer", HTTP_X_FORWARDED_FOR="1.1.1.1", REMOTE_ADDR="127.0.0.1")
    request_2 = rf.get("/qualquer", HTTP_X_FORWARDED_FOR="2.2.2.2", REMOTE_ADDR="127.0.0.1")
    request_1.user = user
    request_2.user = user

    limited_1, _ = check_rate_limit(request_1, scope="auth_scope", limit=1, window_seconds=60)
    limited_2, _ = check_rate_limit(request_2, scope="auth_scope", limit=1, window_seconds=60)

    assert limited_1 is False
    assert limited_2 is True


@pytest.mark.critico
@override_settings(RATE_LIMIT_TRUSTED_PROXIES=set())
def test_rate_limit_anonimo_ignora_x_forwarded_for_sem_proxy_confiavel(rf):
    cache.clear()
    request_1 = rf.get("/qualquer", HTTP_X_FORWARDED_FOR="1.1.1.1", REMOTE_ADDR="127.0.0.10")
    request_2 = rf.get("/qualquer", HTTP_X_FORWARDED_FOR="2.2.2.2", REMOTE_ADDR="127.0.0.10")
    request_1.user = AnonymousUser()
    request_2.user = AnonymousUser()

    limited_1, _ = check_rate_limit(request_1, scope="anon_proxy", limit=1, window_seconds=60)
    limited_2, _ = check_rate_limit(request_2, scope="anon_proxy", limit=1, window_seconds=60)

    assert limited_1 is False
    assert limited_2 is True


@pytest.mark.critico
@override_settings(RATE_LIMIT_TRUSTED_PROXIES={"127.0.0.10"})
def test_rate_limit_anonimo_usa_x_forwarded_for_com_proxy_confiavel(rf):
    cache.clear()
    request_1 = rf.get("/qualquer", HTTP_X_FORWARDED_FOR="1.1.1.1", REMOTE_ADDR="127.0.0.10")
    request_2 = rf.get("/qualquer", HTTP_X_FORWARDED_FOR="2.2.2.2", REMOTE_ADDR="127.0.0.10")
    request_1.user = AnonymousUser()
    request_2.user = AnonymousUser()

    limited_1, _ = check_rate_limit(request_1, scope="trusted_proxy", limit=1, window_seconds=60)
    limited_2, _ = check_rate_limit(request_2, scope="trusted_proxy", limit=1, window_seconds=60)

    assert limited_1 is False
    assert limited_2 is False