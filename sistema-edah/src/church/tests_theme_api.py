import pytest
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def api_client():
    """Fixture do cliente API."""
    return APIClient()


@pytest.fixture
def authenticated_user(db):
    """Criar usuario autenticado para testes."""
    user = User.objects.create_user(
        email="test@example.com",
        password="testpass123",
        nome="Test User"
    )
    return user


@pytest.mark.django_db
class TestThemeAPI:
    """Testes da API de preferencia de tema."""
    
    def test_get_theme_autenticado_retorna_200(self, api_client, authenticated_user):
        """TC-BE-I-01: GET /api/user/theme/ retorna tema do usuario autenticado com 200."""
        api_client.force_authenticate(user=authenticated_user)
        response = api_client.get('/api/user/theme/')
        
        assert response.status_code == status.HTTP_200_OK
        assert 'theme' in response.data
        assert response.data['theme'] == 'light'  # default
    
    def test_get_theme_anonimo_retorna_401(self, api_client):
        """TC-BE-I-02: GET /api/user/theme/ retorna 401 ou 403 para usuario anonimo."""
        response = api_client.get('/api/user/theme/')
        # DRF retorna 403 por padrão quando IsAuthenticated falha
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
    
    def test_patch_theme_valido_retorna_200(self, api_client, authenticated_user):
        """TC-BE-I-03: PATCH /api/user/theme/ atualiza tema com payload valido."""
        api_client.force_authenticate(user=authenticated_user)
        response = api_client.patch(
            '/api/user/theme/',
            {'theme': 'dark'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['theme'] == 'dark'
        
        # Validar persistencia no banco
        authenticated_user.refresh_from_db()
        assert authenticated_user.theme_preference == 'dark'
    
    def test_patch_theme_invalido_retorna_400(self, api_client, authenticated_user):
        """TC-BE-I-04: PATCH /api/user/theme/ rejeita payload invalido com 400."""
        api_client.force_authenticate(user=authenticated_user)
        response = api_client.patch(
            '/api/user/theme/',
            {'theme': 'blue'},  # valor invalido
            format='json'
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'theme' in response.data or 'non_field_errors' in response.data

    def test_patch_theme_sem_campo_theme_retorna_400(self, api_client, authenticated_user):
        """TC-BE-I-06: PATCH /api/user/theme/ sem campo theme deve retornar 400 explicito."""
        api_client.force_authenticate(user=authenticated_user)
        response = api_client.patch(
            '/api/user/theme/',
            {},
            format='json'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['code'] == 'THEME_REQUIRED'
        assert 'accepted_values' in response.data

    def test_patch_theme_com_body_nulo_retorna_400(self, api_client, authenticated_user):
        """TC-BE-I-07: PATCH /api/user/theme/ com body nulo deve retornar 400 explicito."""
        api_client.force_authenticate(user=authenticated_user)
        response = api_client.patch('/api/user/theme/', data=None, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['code'] == 'THEME_REQUIRED'
    
    def test_patch_theme_outro_usuario_bloqueado(self, api_client, db):
        """TC-BE-I-05: usuario nao consegue atualizar tema de outro usuario (sem IDOR)."""
        user1 = User.objects.create_user(
            email="user1@example.com",
            password="pass123",
            nome="User 1"
        )
        user2 = User.objects.create_user(
            email="user2@example.com",
            password="pass123",
            nome="User 2"
        )
        
        # user1 tenta atualizar tema
        api_client.force_authenticate(user=user1)
        response = api_client.patch(
            '/api/user/theme/',
            {'theme': 'dark'},
            format='json'
        )
        
        # Deve atualizar o tema de user1, nao de user2
        assert response.status_code == status.HTTP_200_OK
        user1.refresh_from_db()
        user2.refresh_from_db()
        
        assert user1.theme_preference == 'dark'
        assert user2.theme_preference == 'light'  # nao foi alterado
    
    def test_patch_theme_com_autenticacao_invalida_retorna_401(self, api_client, authenticated_user):
        """BONUS: PATCH sem autenticacao retorna 401 ou 403."""
        response = api_client.patch(
            '/api/user/theme/',
            {'theme': 'dark'},
            format='json'
        )
        
        # DRF retorna 403 por padrão quando IsAuthenticated falha
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
    
    def test_patch_theme_light_persistance(self, api_client, authenticated_user):
        """BONUS: Alternar para light e persistir."""
        # Primeiro mudar para dark
        api_client.force_authenticate(user=authenticated_user)
        api_client.patch(
            '/api/user/theme/',
            {'theme': 'dark'},
            format='json'
        )
        
        # Depois mudar volta para light
        response = api_client.patch(
            '/api/user/theme/',
            {'theme': 'light'},
            format='json'
        )
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['theme'] == 'light'
        
        authenticated_user.refresh_from_db()
        assert authenticated_user.theme_preference == 'light'
