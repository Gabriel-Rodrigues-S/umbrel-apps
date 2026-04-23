"""
Settings de teste — força modo single-tenant (SQLite in-memory).
Usado pelo pytest via DJANGO_SETTINGS_MODULE=config.settings_test.
"""

import os

# Zera DATABASE_URL ANTES do settings.py lê-lo via os.getenv.
# django-environ.Env.read_env usa setdefault, portanto não sobrescreve
# valores já presentes em os.environ.
os.environ["DATABASE_URL"] = ""

# Importa tudo do settings principal (que agora verá DATABASE_URL vazio
# e ativará o modo single-tenant / SQLite).
from config.settings import *  # noqa: F401, F403, E402

# Garante SQLite in-memory mesmo que algo acima tenha escapado
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

MULTI_TENANCY = False

# Remove configurações exclusivas do modo multi-tenant
for _k in ("TENANT_MODEL", "TENANT_DOMAIN_MODEL", "DATABASE_ROUTERS"):
    globals().pop(_k, None)

# Garante que INSTALLED_APPS não inclui django_tenants
INSTALLED_APPS = [
    app for app in INSTALLED_APPS  # noqa: F821
    if "tenants" not in app and "django_tenants" not in app
]

# Desativa o middleware do django-tenants se estiver presente
MIDDLEWARE = [
    mw for mw in MIDDLEWARE  # noqa: F821
    if "TenantMainMiddleware" not in mw
]
