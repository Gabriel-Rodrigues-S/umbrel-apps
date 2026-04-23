"""
Configuração raiz do pytest.

Força o modo single-tenant (SQLite) durante os testes, independentemente do
DATABASE_URL definido no .env. Isso evita a necessidade de um banco PostgreSQL
com permissão de criação de banco de dados no ambiente de desenvolvimento/CI.

A django-environ usa overwrite=False por padrão, portanto definir DATABASE_URL=""
aqui (via pytest_configure, que roda antes do Django setup) impede que o .env
sobrescreva o valor.
"""


def pytest_configure(config):
    import os
    # Força SQLite: DATABASE_URL vazia → MULTI_TENANCY = False → sqlite3
    os.environ["DATABASE_URL"] = ""
