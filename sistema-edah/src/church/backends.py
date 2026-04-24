from django.contrib.auth.backends import ModelBackend
from django.db import connection

try:
    from django_tenants.utils import schema_context
    _HAS_TENANTS = True
except ImportError:
    _HAS_TENANTS = False
    schema_context = None


class PublicSchemaAdminBackend(ModelBackend):
    """
    Permite que superusers do schema público se autentiquem no admin de qualquer schema de tenant.
    Usado para dar ao dono do SaaS acesso ao painel Django de todas as igrejas.

    Em schemas de tenant:
      - Verifica credenciais no schema público.
      - Só autentica se o usuário for superuser ativo no schema público.

    No schema público:
      - Retorna None para não interferir com o ModelBackend padrão.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        # Só atua em modo multi-tenant e em schemas de tenant
        if not _HAS_TENANTS or getattr(connection, 'schema_name', 'public') == 'public':
            return None

        from django.contrib.auth import get_user_model
        User = get_user_model()

        with schema_context('public'):
            try:
                user = User._default_manager.get_by_natural_key(username)
            except User.DoesNotExist:
                # Proteção contra timing attack: executa o hashing de qualquer forma
                User().set_password(password)
                return None

            if (
                user.is_superuser
                and self.user_can_authenticate(user)
                and user.check_password(password)
            ):
                return user

        return None

    def get_user(self, user_id):
        # Só atua em modo multi-tenant e em schemas de tenant
        if not _HAS_TENANTS or getattr(connection, 'schema_name', 'public') == 'public':
            return None

        from django.contrib.auth import get_user_model
        User = get_user_model()

        with schema_context('public'):
            try:
                user = User._default_manager.get(pk=user_id)
                if user.is_superuser and user.is_active:
                    return user
            except User.DoesNotExist:
                pass

        return None
