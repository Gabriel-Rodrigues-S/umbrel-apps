import pytest
from django.urls import reverse


pytestmark = pytest.mark.django_db


@pytest.mark.critico
@pytest.mark.integracao
def test_usuario_update_retorna_404_para_pk_inexistente(client, make_user):
    admin = make_user(
        email="admin@example.com",
        nome="Admin",
        is_staff=True,
        is_superuser=True,
        nivel_acesso="admin",
    )
    client.force_login(admin)

    response = client.get(reverse("configuracoes_usuario_editar", kwargs={"pk": 999999}))

    assert response.status_code == 404
