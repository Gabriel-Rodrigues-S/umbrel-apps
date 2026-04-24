"""
Django settings — django-sis-igreja.

Suporte a dois modos:
  - Single-tenant (SQLite)  → padrão para desenvolvimento local
  - Multi-tenant  (PostgreSQL + django-tenants) → ativado quando DATABASE_URL estiver definida no .env
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

from django.contrib.messages import constants as msg_constants

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── django-environ ──────────────────────────────────────────────────────────
try:
    import environ
    env = environ.Env()
    _env_file = BASE_DIR / ".env"
    if _env_file.exists():
        environ.Env.read_env(_env_file)
    _USE_ENVIRON = True
except ImportError:
    # django-environ ainda não instalado — usar os.getenv como fallback
    _USE_ENVIRON = False

    class _FallbackEnv:
        def str(self, key, default=""):
            return os.getenv(key, default)

        def bool(self, key, default=False):
            val = os.getenv(key, str(default)).strip().lower()
            return val in ("1", "true", "yes")

        def list(self, key, default=None):
            raw = os.getenv(key, "")
            return [v.strip() for v in raw.split(",") if v.strip()] if raw else (default or [])

    env = _FallbackEnv()

# ─── Modo de operação ─────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
MULTI_TENANCY = bool(DATABASE_URL)  # True quando DATABASE_URL (PostgreSQL) está configurada

DJANGO_ENV = os.getenv("DJANGO_ENV", "development").strip().lower()
IS_PRODUCTION = DJANGO_ENV in {"prod", "production"}
IS_TEST_RUNTIME = "test" in sys.argv or "pytest" in " ".join(sys.argv).lower()

DEBUG = os.getenv("DJANGO_DEBUG", "False" if IS_PRODUCTION else "True").strip().lower() == "true"

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if IS_TEST_RUNTIME:
        SECRET_KEY = "django-insecure-test-only-never-use-in-production"
    else:
        raise RuntimeError(
            "DJANGO_SECRET_KEY não configurada. "
            "Gere uma chave com: python -c \"import secrets; print(secrets.token_hex(50))\" "
            "e defina a variável de ambiente DJANGO_SECRET_KEY."
        )

# ─── Segurança ────────────────────────────────────────────────────────────────
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "https://umbrel.tail4ad02c.ts.net",
    ).split(",")
    if origin.strip()
]

ALLOWED_HOSTS: list[str] = [
    host.strip()
    for host in os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,192.168.100.24,100.93.71.51,umbrel.tail4ad02c.ts.net,sistema.sisigreja.com,192.168.100.1,.localhost",
    ).split(",")
    if host.strip()
]

# Em multi-tenancy, aceitar qualquer subdomínio do SaaS
if MULTI_TENANCY:
    ALLOWED_HOSTS.append(".seuapp.com.br")

RATE_LIMIT_TRUSTED_PROXIES: set[str] = {
    host.strip()
    for host in os.getenv("DJANGO_RATE_LIMIT_TRUSTED_PROXIES", "").split(",")
    if host.strip()
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = os.getenv("DJANGO_SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.getenv("DJANGO_CSRF_COOKIE_SAMESITE", "Lax")

if IS_PRODUCTION and not DEBUG:
    secure_ssl_redirect_default = "False" if IS_TEST_RUNTIME else "True"
    SECURE_SSL_REDIRECT = (
        os.getenv("DJANGO_SECURE_SSL_REDIRECT", secure_ssl_redirect_default).strip().lower()
        == "true"
    )
    SESSION_COOKIE_SECURE = os.getenv("DJANGO_SESSION_COOKIE_SECURE", "True").strip().lower() == "true"
    CSRF_COOKIE_SECURE = os.getenv("DJANGO_CSRF_COOKIE_SECURE", "True").strip().lower() == "true"
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = (
        os.getenv("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "True").strip().lower() == "true"
    )
    SECURE_HSTS_PRELOAD = os.getenv("DJANGO_SECURE_HSTS_PRELOAD", "True").strip().lower() == "true"
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = os.getenv(
        "DJANGO_SECURE_REFERRER_POLICY", "strict-origin-when-cross-origin"
    )
    X_FRAME_OPTIONS = os.getenv("DJANGO_X_FRAME_OPTIONS", "DENY")

# ─── Apps e banco ─────────────────────────────────────────────────────────────
if MULTI_TENANCY:
    # ── Multi-tenant (PostgreSQL + django-tenants) ────────────────────────────
    SHARED_APPS = [
        # django-tenants deve ser o primeiro
        "django_tenants",
        # App com os models Igreja e Domain (schema public)
        "church.tenants",
        # Apps Django padrão no schema public
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "django.contrib.admin",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        # Infraestrutura
        "corsheaders",
        "whitenoise.runserver_nostatic",
        # church deve estar em SHARED_APPS porque AUTH_USER_MODEL = "church.User"
        # O TenantSyncRouter bloquearia a criação da tabela "usuarios" no schema
        # public se church ficasse apenas em TENANT_APPS, quebrando auth e admin.
        "church",
        "rest_framework",
        "rest_framework_simplejwt",
        "rest_framework_simplejwt.token_blacklist",
    ]

    TENANT_APPS = [
        # Tudo específico por igreja vai aqui
        "church",
        "rest_framework",
        "rest_framework_simplejwt",
        "rest_framework_simplejwt.token_blacklist",
    ]

    INSTALLED_APPS = list(SHARED_APPS) + [
        app for app in TENANT_APPS if app not in SHARED_APPS
    ]

    TENANT_MODEL = "tenants.Igreja"
    TENANT_DOMAIN_MODEL = "tenants.Domain"

    import environ as _environ
    _env = _environ.Env()
    DATABASES = {
        "default": {
            **_env.db("DATABASE_URL"),
            "ENGINE": "django_tenants.postgresql_backend",
        }
    }
    DATABASE_ROUTERS = ["django_tenants.routers.TenantSyncRouter"]

    MIDDLEWARE = [
        # TenantMainMiddleware DEVE ser o primeiro
        "django_tenants.middleware.main.TenantMainMiddleware",
        "corsheaders.middleware.CorsMiddleware",
        "django.middleware.security.SecurityMiddleware",
        "whitenoise.middleware.WhiteNoiseMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
    ]

    ROOT_URLCONF = "config.urls"
    PUBLIC_SCHEMA_URLCONF = "config.urls_public"

else:
    # ── Single-tenant (SQLite) — desenvolvimento local ────────────────────────
    INSTALLED_APPS = [
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "corsheaders",
        "rest_framework",
        "rest_framework_simplejwt",
        "rest_framework_simplejwt.token_blacklist",
        "church",
    ]

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

    MIDDLEWARE = [
        "corsheaders.middleware.CorsMiddleware",
        "django.middleware.security.SecurityMiddleware",
        "whitenoise.middleware.WhiteNoiseMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
    ]

    ROOT_URLCONF = "config.urls"

# ─── Autenticação ─────────────────────────────────────────────────────────────
# PublicSchemaAdminBackend permite que o dono do SaaS (superuser do schema público)
# acesse o painel admin Django em qualquer subdomínio de igreja.
# Em schemas de tenant retorna None se não for superuser do público, sem interferir.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "church.backends.PublicSchemaAdminBackend",
]

# ─── Templates ────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ─── Autenticação ─────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "church.User"

# ─── Internacionalização ──────────────────────────────────────────────────────
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# ─── Arquivos estáticos e mídia ───────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "uploads/"
MEDIA_ROOT = BASE_DIR / "uploads"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Login / redirect ─────────────────────────────────────────────────────────
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

MESSAGE_TAGS = {
    msg_constants.DEBUG:   "secondary",
    msg_constants.INFO:    "info",
    msg_constants.SUCCESS: "success",
    msg_constants.WARNING: "warning",
    msg_constants.ERROR:   "danger",
}

# ─── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DJANGO_CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:5500,http://localhost:8080,http://localhost:44203",
    ).split(",")
    if origin.strip()
]
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True

# ─── REST Framework ───────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}
