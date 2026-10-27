import time

import pytest

from alertas import banco


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def con(tmp_path):
    c = banco.abrir(tmp_path / "alertas.db")
    yield c
    c.close()


def inserir_em(con, dias_atras, gravidade="normal"):
    """Ajudante de teste: alerta com data no passado."""
    return banco.inserir(con, "gateway", gravidade, "antigo", "",
                         criado_em=time.time() - dias_atras * 86400)
