from django.db import connection
from rest_framework.permissions import BasePermission

from church.tenants.models import Igreja


def get_tenant() -> "Igreja | None":
    """Retorna o tenant (Igreja) do schema ativo na requisição atual."""
    schema = connection.schema_name
    try:
        return Igreja.objects.using("default").get(schema_name=schema)
    except Igreja.DoesNotExist:
        return None


def assinatura_permite() -> bool:
    """Retorna True se a assinatura da igreja atual está ativa e dentro do prazo."""
    tenant = get_tenant()
    if tenant is None:
        return True  # schema público — sem restrições
    return tenant.assinatura_ativa


class IsAssinaturaAtiva(BasePermission):
    """
    Permission que bloqueia acesso quando a assinatura da igreja está inativa
    ou vencida. Use em conjunto com IsAuthenticated nas views de API.
    """
    message = "A assinatura desta igreja está inativa. Entre em contato com o administrador."

    def has_permission(self, request, view):
        return assinatura_permite()
