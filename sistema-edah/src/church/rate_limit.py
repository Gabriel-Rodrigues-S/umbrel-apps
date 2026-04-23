import math
import time

from django.conf import settings
from django.core.cache import cache


DEFAULT_WINDOW_SECONDS = 60


def _client_ip(request) -> str:
    remote_addr = request.META.get("REMOTE_ADDR", "unknown")
    trusted_proxies = getattr(settings, "RATE_LIMIT_TRUSTED_PROXIES", set())
    if remote_addr not in trusted_proxies:
        return remote_addr

    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return remote_addr


def _subject_identifier(request) -> str:
    if getattr(request.user, "is_authenticated", False):
        return f"u:{request.user.pk}"
    return f"ip:{_client_ip(request)}"


def _cache_key(scope: str, subject: str) -> str:
    return f"rate_limit:{scope}:{subject}"


def _count_key(scope: str, subject: str) -> str:
    return f"{_cache_key(scope, subject)}:count"


def _reset_key(scope: str, subject: str) -> str:
    return f"{_cache_key(scope, subject)}:reset_at"


def check_rate_limit(request, scope: str, limit: int, window_seconds: int = DEFAULT_WINDOW_SECONDS):
    now = time.time()
    subject = _subject_identifier(request)
    count_key = _count_key(scope, subject)
    reset_key = _reset_key(scope, subject)

    reset_at = cache.get(reset_key)
    if reset_at is None or float(reset_at) <= now:
        # add() evita sobrescrever uma janela recém-criada por outra requisição concorrente.
        if cache.add(reset_key, now + window_seconds, timeout=window_seconds):
            cache.set(count_key, 0, timeout=window_seconds)

    reset_at = float(cache.get(reset_key, now + window_seconds))
    remaining_ttl = max(1, math.ceil(reset_at - now))
    cache.add(count_key, 0, timeout=remaining_ttl)
    try:
        count = int(cache.incr(count_key))
    except ValueError:
        cache.set(count_key, 1, timeout=remaining_ttl)
        count = 1

    if count > limit:
        retry_after = max(1, math.ceil(reset_at - now))
        return True, retry_after

    return False, 0


def reset_rate_limit(request, scope: str) -> None:
    subject = _subject_identifier(request)
    cache.delete_many([
        _count_key(scope, subject),
        _reset_key(scope, subject),
    ])
