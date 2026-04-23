import json
import logging
from collections.abc import Iterable

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.http import require_GET, require_POST

logger = logging.getLogger(__name__)

from church.models import Mensagem
from church.rate_limit import check_rate_limit

User = get_user_model()
MAX_CHAT_MENSAGEM_CHARS = 2000
CHAT_PING_MAX_USUARIOS = 100
RATE_LIMIT_CHAT_PING = 120
RATE_LIMIT_CHAT_MENSAGENS = 180
RATE_LIMIT_CHAT_ENVIAR = 60
RATE_LIMIT_CHAT_WINDOW_SECONDS = 60


def _rate_limited_response(retry_after: int) -> JsonResponse:
    response = JsonResponse({"ok": False, "erro": "rate_limited"}, status=429)
    response["Retry-After"] = str(retry_after)
    return response


def _build_contact_ids(user_id: int, rows: Iterable[tuple[int, int]]) -> set[int]:
    contact_ids: set[int] = set()
    for remetente_id, destinatario_id in rows:
        if remetente_id == user_id and destinatario_id != user_id:
            contact_ids.add(destinatario_id)
        elif destinatario_id == user_id and remetente_id != user_id:
            contact_ids.add(remetente_id)
    return contact_ids


@login_required
@require_GET
def chat_ping(request):
    is_limited, retry_after = check_rate_limit(
        request,
        scope="chat_ping",
        limit=RATE_LIMIT_CHAT_PING,
        window_seconds=RATE_LIMIT_CHAT_WINDOW_SECONDS,
    )
    if is_limited:
        return _rate_limited_response(retry_after)

    conversa_rows = (
        Mensagem.objects.filter(Q(remetente=request.user) | Q(destinatario=request.user))
        .values_list("remetente_id", "destinatario_id")
        .iterator()
    )
    contato_ids = _build_contact_ids(request.user.pk, conversa_rows)

    unread_counts = list(
        Mensagem.objects.filter(destinatario=request.user, lida=False)
        .values("remetente_id")
        .annotate(total=Count("id"))
    )
    unread_sender_ids = {row["remetente_id"] for row in unread_counts}
    contato_ids.update(unread_sender_ids)

    usuarios = (
        User.objects.filter(is_active=True, pk__in=contato_ids)
        .exclude(pk=request.user.pk)
        .values("id", "nome")[:CHAT_PING_MAX_USUARIOS]
    )
    lista = [
        {"id": u["id"], "nome": u["nome"] or f"Usuario {u['id']}", "online": False}
        for u in usuarios
    ]
    nao_lidas = {row["remetente_id"]: row["total"] for row in unread_counts}
    return JsonResponse({"ok": True, "usuarios": lista, "nao_lidas": nao_lidas})


@login_required
@require_GET
def chat_mensagens(request):
    is_limited, retry_after = check_rate_limit(
        request,
        scope="chat_mensagens",
        limit=RATE_LIMIT_CHAT_MENSAGENS,
        window_seconds=RATE_LIMIT_CHAT_WINDOW_SECONDS,
    )
    if is_limited:
        return _rate_limited_response(retry_after)

    com_id = request.GET.get("com")
    if not com_id:
        return JsonResponse({"ok": False, "mensagens": []})
    try:
        desde = int(request.GET.get("desde") or 0)
        com_id = int(com_id)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "mensagens": []}, status=400)
    if com_id <= 0 or desde < 0:
        return JsonResponse({"ok": False, "mensagens": []}, status=400)
    qs = Mensagem.objects.filter(
        Q(remetente=request.user, destinatario_id=com_id)
        | Q(remetente_id=com_id, destinatario=request.user)
    ).order_by("id")
    if desde:
        qs = qs.filter(id__gt=desde)
    msgs = [
        {
            "id": m.id,
            "remetente_id": m.remetente_id,
            "mensagem": m.mensagem,
            "criado_em": timezone.localtime(m.data_envio).strftime("%Y-%m-%d %H:%M:%S"),
        }
        for m in qs[:200]
    ]
    return JsonResponse({"ok": True, "mensagens": msgs})


@login_required
@require_POST
def chat_enviar(request):
    is_limited, retry_after = check_rate_limit(
        request,
        scope="chat_enviar",
        limit=RATE_LIMIT_CHAT_ENVIAR,
        window_seconds=RATE_LIMIT_CHAT_WINDOW_SECONDS,
    )
    if is_limited:
        return _rate_limited_response(retry_after)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"ok": False}, status=400)
    try:
        dest_id = int(data.get("destinatario_id") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False}, status=400)
    texto = (data.get("mensagem") or "").strip()
    if not dest_id or not texto:
        return JsonResponse({"ok": False}, status=400)
    if len(texto) > MAX_CHAT_MENSAGEM_CHARS:
        return JsonResponse({"ok": False}, status=400)
    if request.user.pk == dest_id:
        return JsonResponse({"ok": False}, status=400)
    dest = User.objects.filter(pk=dest_id).first()
    if not dest:
        return JsonResponse({"ok": False}, status=404)
    # Sanitiza contra XSS antes de persistir
    texto = escape(texto)
    m = Mensagem.objects.create(
        remetente=request.user,
        destinatario=dest,
        mensagem=texto,
    )
    return JsonResponse(
        {
            "ok": True,
            "id": m.id,
            "criado_em": timezone.localtime(m.data_envio).strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
