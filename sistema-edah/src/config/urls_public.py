"""
URLs do schema público (super-admin do SaaS).
Acessível em: admin.seuapp.com.br

Gerencia:
  - Painel Django admin para criação/gestão de igrejas (tenants)
  - Endpoint público de resolução de código de acesso para o app Flutter
"""

from django.contrib import admin
from django.core.cache import cache
from django.http import JsonResponse
from django.urls import path
from django.views.generic import RedirectView

# Rate limit: máximo de tentativas por janela de tempo por IP
_RATE_LIMIT_MAX = 20
_RATE_LIMIT_WINDOW = 60  # segundos


def _get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def resolver_codigo(request):
    """
    GET /api/resolver/?codigo=IBMANAUS

    Retorna o domínio e nome da igreja associada ao código de acesso.
    Usado pelo app Flutter na primeira abertura para descobrir o subdomínio correto.
    """
    ip = _get_client_ip(request)
    cache_key = f"resolver_codigo_rl:{ip}"
    tentativas = cache.get(cache_key, 0)
    if tentativas >= _RATE_LIMIT_MAX:
        return JsonResponse({"erro": "Muitas tentativas. Tente novamente em instantes."}, status=429)
    cache.set(cache_key, tentativas + 1, timeout=_RATE_LIMIT_WINDOW)

    from church.tenants.models import Domain, Igreja

    codigo = request.GET.get("codigo", "").strip().upper()
    if not codigo:
        return JsonResponse({"erro": "Parâmetro 'codigo' obrigatório."}, status=400)

    try:
        igreja = Igreja.objects.get(codigo_acesso=codigo, ativo=True)
    except Igreja.DoesNotExist:
        # Resposta uniforme para não vazar diferença entre "inválido" e "inativo"
        return JsonResponse({"erro": "Código não encontrado."}, status=404)

    domain = Domain.objects.filter(tenant=igreja, is_primary=True).first()
    if not domain:
        return JsonResponse({"erro": "Nenhum domínio configurado para esta igreja."}, status=404)

    return JsonResponse({
        "dominio": domain.domain,
        "nome": igreja.nome,
        "assinatura_ativa": igreja.assinatura_ativa,
    })


def resolver_tenant_path(request, codigo):
    """
    GET /api/v1/public/tenant/{codigo}/

    Adapter: converte o path param em query param e delega ao resolver_codigo,
    reutilizando toda a lógica de rate-limit e validação já existente.
    """
    get = request.GET.copy()
    get["codigo"] = codigo.upper()
    request.GET = get
    return resolver_codigo(request)


urlpatterns = [
    # Painel super-admin do dono do SaaS
    path("admin/", admin.site.urls),
    # Endpoint de resolução de código para o app Flutter (query-param — legado)
    path("api/resolver/", resolver_codigo, name="resolver_codigo"),
    # Endpoint de resolução de código para o app Flutter (path param — spec v1)
    path("api/v1/public/tenant/<str:codigo>/", resolver_tenant_path, name="resolver_tenant_path"),
    # Logout do admin redireciona para "login" — aponta para o login do admin
    path("login/", RedirectView.as_view(url="/admin/login/"), name="login"),
]
