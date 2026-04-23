from church.models import Membro, StatusMembro
from rest_framework.permissions import BasePermission


class IsMembroAtivo(BasePermission):
    """Permite acesso apenas a usuário autenticado com membro ativo."""

    message = "Acesso restrito a membros ativos."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        return Membro.objects.filter(
            pessoa__email=user.email,
            status=StatusMembro.ATIVO,
        ).exists()


class IsAdminIgreja(BasePermission):
    """
    Permite acesso a usuários com papel de gestão da igreja:
    ADMIN, PASTOR, LIDER, SECRETARIA, FINANCEIRO.
    Exclui USUARIO (membro comum do app).
    """
    message = "Acesso restrito a administradores da igreja."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        from church.models import NivelAcesso
        return user.nivel_acesso in {
            NivelAcesso.ADMIN,
            NivelAcesso.PASTOR,
            NivelAcesso.LIDER,
            NivelAcesso.SECRETARIA,
            NivelAcesso.FINANCEIRO,
        }


class IsFinanceiroIgreja(BasePermission):
    """
    Permite acesso apenas a usuários com papel financeiro:
    ADMIN, PASTOR, FINANCEIRO.
    """
    message = "Acesso restrito ao setor financeiro."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        from church.models import NivelAcesso
        return user.nivel_acesso in {
            NivelAcesso.ADMIN,
            NivelAcesso.PASTOR,
            NivelAcesso.FINANCEIRO,
        }


class CanCreateMembers(BasePermission):
    """
    Permite criar e editar membros apenas a ADMIN e PASTOR.
    LIDER e SECRETARIA podem consultar (via IsAdminIgreja),
    mas não criar ou alterar registros de membros.
    """
    message = "Somente administradores e pastores podem criar ou editar membros."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        from church.models import NivelAcesso
        return user.nivel_acesso in {
            NivelAcesso.ADMIN,
            NivelAcesso.PASTOR,
        }
