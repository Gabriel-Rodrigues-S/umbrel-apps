from django.apps import AppConfig


class ChurchConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'church'

    def ready(self):
        self._patch_admin_has_permission()

    @staticmethod
    def _patch_admin_has_permission():
        """
        Garante que o painel admin Django em schemas de tenant só seja acessível
        pelo dono do SaaS (superuser autenticado via PublicSchemaAdminBackend).
        Superusers de cada igreja não conseguem acessar o admin Django.
        """
        from django.contrib.admin import AdminSite
        from django.db import connection

        _TENANT_BACKEND = 'church.backends.PublicSchemaAdminBackend'
        _original_has_permission = AdminSite.has_permission

        def has_permission(self, request):
            schema = getattr(connection, 'schema_name', 'public')
            if schema == 'public':
                return _original_has_permission(self, request)
            # Em schemas de tenant: só o dono do SaaS pode acessar o admin
            if not getattr(request.user, 'is_active', False):
                return False
            if not getattr(request.user, 'is_superuser', False):
                return False
            backend = request.session.get('_auth_user_backend', '')
            return backend == _TENANT_BACKEND

        AdminSite.has_permission = has_permission
