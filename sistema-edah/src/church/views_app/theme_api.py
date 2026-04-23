from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
import logging

from church.models.user import TemaPreferencia
from church.serializers import ThemePreferenceSerializer


logger = logging.getLogger(__name__)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def user_theme_view(request):
    """
    GET /api/user/theme/
    - Retorna tema atual do usuario autenticado
    
    PATCH /api/user/theme/
    - Atualiza preferencia de tema
    - Body: {"theme": "light" | "dark"}
    """
    user = request.user
    
    if request.method == 'GET':
        serializer = ThemePreferenceSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'PATCH':
        if 'theme' not in request.data:
            return Response(
                {
                    "code": "THEME_REQUIRED",
                    "detail": "O campo 'theme' e obrigatorio.",
                    "accepted_values": [TemaPreferencia.CLARO, TemaPreferencia.ESCURO],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ThemePreferenceSerializer(user, data=request.data, partial=False)
        if serializer.is_valid():
            try:
                serializer.save()
            except Exception:
                logger.exception(
                    "Erro ao persistir preferencia de tema.",
                    extra={"user_id": user.id},
                )
                return Response(
                    {
                        "code": "THEME_UPDATE_FAILED",
                        "detail": "Nao foi possivel salvar a preferencia de tema no momento.",
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response(serializer.data, status=status.HTTP_200_OK)

        logger.warning(
            "Payload invalido para atualizacao de tema.",
            extra={"user_id": user.id, "errors": serializer.errors},
        )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def theme_health_check(request):
    """
    GET /api/health/theme/
    - Simples health check para validar persistencia de tema em log
    - Nao requer autenticacao
    """
    return Response(
        {"status": "ok", "message": "Theme API is operational"},
        status=status.HTTP_200_OK
    )
