import logging

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

logger = logging.getLogger(__name__)

from church.api_serializers import (
    AdminMembroCreateSerializer,
    AdminMembroListSerializer,
    AdminMembroPatchSerializer,
    AdminVisitanteSerializer,
    ChatContatoSerializer,
    ChatMensagemSerializer,
    ClasseSerializer,
    ConfiguracaoIgrejaSerializer,
    CursoMatriculaSerializer,
    CursoSerializer,
    DiscipuladoSerializer,
    DispositivoFCMSerializer,
    EventoInscricaoAdminSerializer,
    EventoListSerializer,
    GaleriaFotoSerializer,
    GaleriaSerializer,
    GrupoDetalheSerializer,
    GrupoResumoSerializer,
    LancamentoFinanceiroSerializer,
    MembroMeMembroSerializer,
    MembroMePessoaSerializer,
    MembroMeUpdateSerializer,
    MinisterioDetalheSerializer,
    MinisterioResumoSerializer,
    NoticiaSerializer,
    PedidoOracaoSerializer,
    UsuarioResumoSerializer,
    eventos_publicados_queryset,
    familia_do_membro,
    galerias_publicadas_queryset,
    grupos_do_membro_queryset,
    ministerios_do_membro_queryset,
    noticias_publicadas_queryset,
)
from church.models import (
    ClasseAluno,
    ClasseEstudo,
    ConfiguracaoIgreja,
    Curso,
    CursoMatricula,
    CursoNota,
    CursoPresenca,
    Discipulado,
    DispositivoFCM,
    Evento,
    EventoInscricao,
    Galeria,
    LancamentoFinanceiro,
    Mensagem,
    Ministerio,
    Membro,
    NivelAcesso,
    PedidoOracao,
    Pessoa,
    PequenoGrupo,
    StatusCurso,
    StatusDiscipulado,
    StatusEvento,
    StatusMembro,
    TipoPessoa,
    TipoLancamento,
    User,
    Visitante,
)
from church.permissions import CanCreateMembers, IsAdminIgreja, IsFinanceiroIgreja, IsMembroAtivo
from church.rate_limit import check_rate_limit
from church.views_app.chat_api import MAX_CHAT_MENSAGEM_CHARS

RATE_LIMIT_AUTH_TENTATIVAS = 5
RATE_LIMIT_AUTH_WINDOW_SECONDS = 60


class DefaultPagination(PageNumberPagination):
    page_size = 20


def _get_pessoa(user):
    """Busca a Pessoa associada ao usuário, com cache por request para evitar queries repetidas."""
    if not hasattr(user, "_cached_pessoa"):
        user._cached_pessoa = Pessoa.objects.filter(email=user.email).first()
    return user._cached_pessoa


def _membro_ativo_or_none(user):
    pessoa = _get_pessoa(user)
    if not pessoa:
        return None, None
    membro = Membro.objects.filter(pessoa=pessoa, status=StatusMembro.ATIVO).first()
    return pessoa, membro


@api_view(["POST"])
@permission_classes([AllowAny])
def auth_token_view(request):
    is_limited, retry_after = check_rate_limit(
        request,
        scope="api_login",
        limit=RATE_LIMIT_AUTH_TENTATIVAS,
        window_seconds=RATE_LIMIT_AUTH_WINDOW_SECONDS,
    )
    if is_limited:
        return Response(
            {"detail": "Muitas tentativas. Tente novamente em instantes."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
        )

    email = (request.data.get("email") or "").strip()
    password = request.data.get("password") or ""

    if not email or not password:
        return Response({"detail": "Email e senha são obrigatórios."}, status=status.HTTP_400_BAD_REQUEST)

    serializer = TokenObtainPairSerializer(data={"email": email, "password": password})
    serializer.is_valid(raise_exception=True)

    user = User.objects.filter(email=email).first()
    _, membro = _membro_ativo_or_none(user)
    if not membro:
        logger.warning("Login negado — membro inativo ou não encontrado. Email: %s", email)
        return Response(
            {"detail": "Acesso restrito a membros ativos."},
            status=status.HTTP_403_FORBIDDEN,
        )

    return Response(
        {
            "access": serializer.validated_data["access"],
            "refresh": serializer.validated_data["refresh"],
            "usuario": UsuarioResumoSerializer(user).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def auth_codigo_view(request):
    is_limited, retry_after = check_rate_limit(
        request,
        scope="api_codigo",
        limit=RATE_LIMIT_AUTH_TENTATIVAS,
        window_seconds=RATE_LIMIT_AUTH_WINDOW_SECONDS,
    )
    if is_limited:
        from church.rate_limit import _client_ip
        logger.warning("Rate limit atingido no login por código. IP: %s", _client_ip(request))
        return Response(
            {"detail": "Muitas tentativas. Tente novamente em instantes."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
        )

    codigo = (request.data.get("codigo") or "").strip().upper()
    if not codigo:
        return Response({"detail": "Código obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

    membro = (
        Membro.objects
        .select_related("pessoa")
        .filter(codigo_acesso=codigo, status=StatusMembro.ATIVO)
        .first()
    )
    if not membro:
        from church.rate_limit import _client_ip
        logger.warning("Tentativa de login com código inválido. IP: %s", _client_ip(request))
        return Response(
            {"detail": "Código inválido ou membro inativo."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    pessoa = membro.pessoa
    if not pessoa.email:
        return Response(
            {"detail": "Cadastro sem e-mail. Contate o administrador da igreja."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user, _ = User.objects.get_or_create(
        email=pessoa.email,
        defaults={"nome": pessoa.nome, "nivel_acesso": NivelAcesso.USUARIO},
    )

    refresh = RefreshToken.for_user(user)
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "usuario": UsuarioResumoSerializer(user).data,
    }, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsMembroAtivo])
def auth_logout_view(request):
    refresh = request.data.get("refresh")
    if not refresh:
        return Response({"detail": "Campo refresh é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        token = RefreshToken(refresh)
        token.blacklist()
    except TokenError:
        return Response({"detail": "Refresh token inválido."}, status=status.HTTP_400_BAD_REQUEST)

    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "PATCH"])
@permission_classes([IsMembroAtivo])
def membro_me_view(request):
    pessoa = _get_pessoa(request.user)
    membro = Membro.objects.filter(pessoa=pessoa).first() if pessoa else None
    if not pessoa or not membro:
        return Response({"detail": "Membro não encontrado."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(
            {
                "pessoa": MembroMePessoaSerializer(pessoa).data,
                "membro": MembroMeMembroSerializer(membro).data,
            },
            status=status.HTTP_200_OK,
        )

    serializer = MembroMeUpdateSerializer(pessoa, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(
        {
            "pessoa": MembroMePessoaSerializer(pessoa).data,
            "membro": MembroMeMembroSerializer(membro).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def eventos_list_view(request):
    pessoa = _get_pessoa(request.user)
    qs = eventos_publicados_queryset()
    paginator = DefaultPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = EventoListSerializer(page, many=True, context={"pessoa": pessoa})
    return paginator.get_paginated_response(serializer.data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def eventos_detail_view(request, evento_id):
    pessoa = _get_pessoa(request.user)
    evento = eventos_publicados_queryset().filter(pk=evento_id).first()
    if not evento:
        return Response({"detail": "Evento não encontrado."}, status=status.HTTP_404_NOT_FOUND)
    return Response(EventoListSerializer(evento, context={"pessoa": pessoa}).data)


@api_view(["POST", "DELETE"])
@permission_classes([IsMembroAtivo])
def evento_inscricao_view(request, evento_id):
    pessoa = _get_pessoa(request.user)

    if request.method == "POST":
        with transaction.atomic():
            evento = (
                eventos_publicados_queryset()
                .select_for_update()
                .filter(pk=evento_id)
                .first()
            )
            if not evento:
                return Response({"detail": "Evento não encontrado."}, status=status.HTTP_404_NOT_FOUND)

            if evento.status != StatusEvento.ABERTO:
                return Response({"detail": "Evento não está aberto para inscrição."}, status=status.HTTP_400_BAD_REQUEST)

            if evento.capacidade_maxima and evento.inscricoes.count() >= evento.capacidade_maxima:
                return Response({"detail": "Vagas esgotadas."}, status=status.HTTP_400_BAD_REQUEST)

            inscricao, created = EventoInscricao.objects.get_or_create(evento=evento, pessoa=pessoa)

        return Response(
            {
                "inscrito": True,
                "id": inscricao.id,
                "created": created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    evento = eventos_publicados_queryset().filter(pk=evento_id).first()
    if not evento:
        return Response({"detail": "Evento não encontrado."}, status=status.HTTP_404_NOT_FOUND)
    deleted, _ = EventoInscricao.objects.filter(evento=evento, pessoa=pessoa).delete()
    return Response({"inscrito": False, "deleted": deleted > 0}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def evento_inscricao_status_view(request, evento_id):
    pessoa = _get_pessoa(request.user)
    inscrito = EventoInscricao.objects.filter(evento_id=evento_id, pessoa=pessoa).exists()
    return Response({"inscrito": inscrito}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def noticias_list_view(request):
    qs = noticias_publicadas_queryset()
    paginator = DefaultPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = NoticiaSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def noticias_detail_view(request, noticia_id):
    noticia = noticias_publicadas_queryset().filter(pk=noticia_id).first()
    if not noticia:
        return Response({"detail": "Notícia não encontrada."}, status=status.HTTP_404_NOT_FOUND)
    return Response(NoticiaSerializer(noticia).data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def grupos_meus_view(request):
    pessoa = _get_pessoa(request.user)
    qs = grupos_do_membro_queryset(pessoa)
    return Response(GrupoResumoSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def grupos_detail_view(request, grupo_id):
    grupo = PequenoGrupo.objects.filter(pk=grupo_id).annotate(membros_count=Count("membros")).first()
    if not grupo:
        return Response({"detail": "Grupo não encontrado."}, status=status.HTTP_404_NOT_FOUND)
    return Response(GrupoDetalheSerializer(grupo).data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def ministerios_meus_view(request):
    pessoa = _get_pessoa(request.user)
    qs = ministerios_do_membro_queryset(pessoa)
    return Response(MinisterioResumoSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def ministerios_detail_view(request, ministerio_id):
    ministerio = Ministerio.objects.filter(pk=ministerio_id).annotate(membros_count=Count("membros_vinculos")).first()
    if not ministerio:
        return Response({"detail": "Ministério não encontrado."}, status=status.HTTP_404_NOT_FOUND)
    return Response(MinisterioDetalheSerializer(ministerio).data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def cursos_list_view(request):
    pessoa = _get_pessoa(request.user)
    qs = Curso.objects.filter(status=StatusCurso.ATIVO).order_by("nome")
    paginator = DefaultPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = CursoSerializer(page, many=True, context={"pessoa": pessoa})
    return paginator.get_paginated_response(serializer.data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def cursos_detail_view(request, curso_id):
    pessoa = _get_pessoa(request.user)
    curso = Curso.objects.filter(pk=curso_id).first()
    if not curso:
        return Response({"detail": "Curso não encontrado."}, status=status.HTTP_404_NOT_FOUND)
    return Response(CursoSerializer(curso, context={"pessoa": pessoa}).data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def cursos_minhas_matriculas_view(request):
    pessoa = _get_pessoa(request.user)
    qs = CursoMatricula.objects.filter(pessoa=pessoa).select_related("curso").order_by("-id")
    return Response(CursoMatriculaSerializer(qs, many=True).data)


@api_view(["POST"])
@permission_classes([IsMembroAtivo])
def curso_matricula_view(request, curso_id):
    pessoa = _get_pessoa(request.user)
    curso = Curso.objects.filter(pk=curso_id, status=StatusCurso.ATIVO).first()
    if not curso:
        return Response({"detail": "Curso não encontrado ou inativo."}, status=status.HTTP_404_NOT_FOUND)

    matricula, created = CursoMatricula.objects.get_or_create(
        curso=curso,
        pessoa=pessoa,
        defaults={"data_matricula": timezone.localdate()},
    )
    payload = CursoMatriculaSerializer(matricula).data
    return Response(payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def curso_matricula_progresso_view(request, matricula_id):
    pessoa = _get_pessoa(request.user)
    matricula = CursoMatricula.objects.filter(pk=matricula_id, pessoa=pessoa).first()
    if not matricula:
        return Response({"detail": "Matrícula não encontrada."}, status=status.HTTP_404_NOT_FOUND)

    presencas = list(
        CursoPresenca.objects.filter(matricula=matricula)
        .values("aula_id", "presente", "data_aula")
        .order_by("data_aula")
    )
    notas = list(
        CursoNota.objects.filter(matricula=matricula)
        .values("modulo_id", "nota", "data_avaliacao")
        .order_by("modulo_id")
    )
    return Response({"matricula_id": matricula.id, "presencas": presencas, "notas": notas})


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def discipulado_meu_view(request):
    pessoa = _get_pessoa(request.user)
    discipulado = (
        Discipulado.objects.filter(discipulo=pessoa, status=StatusDiscipulado.EM_ANDAMENTO)
        .select_related("discipulador", "discipulo")
        .first()
    )
    if not discipulado:
        return Response({"discipulado": None}, status=status.HTTP_200_OK)
    return Response(DiscipuladoSerializer(discipulado).data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def classes_minhas_view(request):
    pessoa = _get_pessoa(request.user)
    classes_ids = ClasseAluno.objects.filter(pessoa=pessoa).values_list("classe_id", flat=True)
    qs = ClasseEstudo.objects.filter(id__in=classes_ids).order_by("nome")
    return Response(ClasseSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def classes_detail_view(request, classe_id):
    classe = ClasseEstudo.objects.filter(pk=classe_id).first()
    if not classe:
        return Response({"detail": "Classe não encontrada."}, status=status.HTTP_404_NOT_FOUND)
    return Response(ClasseSerializer(classe).data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def familia_minha_view(request):
    pessoa = _get_pessoa(request.user)
    familia = familia_do_membro(pessoa)
    if not familia:
        return Response({"familia": None, "membros": []}, status=status.HTTP_200_OK)

    membros = [
        {
            "nome": fm.pessoa.nome,
            "parentesco": fm.parentesco,
            "tipo": fm.pessoa.tipo,
        }
        for fm in familia.membros.select_related("pessoa").all()
    ]
    payload = {
        "familia": {
            "id": familia.id,
            "nome_familia": familia.nome_familia,
            "responsavel": familia.responsavel.nome if familia.responsavel else None,
        },
        "membros": membros,
    }
    return Response(payload)


@api_view(["GET", "POST"])
@permission_classes([IsMembroAtivo])
def oracao_view(request):
    pessoa = _get_pessoa(request.user)

    if request.method == "GET":
        pedidos = PedidoOracao.objects.filter(pessoa=pessoa).order_by("-data_pedido")
        return Response(PedidoOracaoSerializer(pedidos, many=True).data)

    serializer = PedidoOracaoSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    pedido = serializer.save(
        pessoa=pessoa,
        nome=pessoa.nome,
        email=pessoa.email,
        telefone=pessoa.telefone,
    )
    return Response(PedidoOracaoSerializer(pedido).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsMembroAtivo])
def oracao_detail_view(request, pedido_id):
    pessoa = _get_pessoa(request.user)
    pedido = PedidoOracao.objects.filter(pk=pedido_id, pessoa=pessoa).first()
    if not pedido:
        return Response({"detail": "Pedido não encontrado."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return Response(PedidoOracaoSerializer(pedido).data)

    if request.method == "PATCH":
        serializer = PedidoOracaoSerializer(pedido, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(PedidoOracaoSerializer(pedido).data)

    pedido.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def galeria_list_view(request):
    qs = galerias_publicadas_queryset()
    paginator = DefaultPagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = GaleriaSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def galeria_fotos_view(request, galeria_id):
    galeria = Galeria.objects.filter(pk=galeria_id, publicar_app=True).first()
    if not galeria:
        return Response({"detail": "Galeria não encontrada."}, status=status.HTTP_404_NOT_FOUND)
    fotos = galeria.fotos.all().order_by("ordem", "id")
    return Response(GaleriaFotoSerializer(fotos, many=True).data)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def chat_contatos_view(request):
    usuario = request.user
    contato_ids = set(
        Mensagem.objects.filter(Q(remetente=usuario) | Q(destinatario=usuario))
        .values_list("remetente_id", "destinatario_id")
    )
    ids = set()
    for remetente_id, destinatario_id in contato_ids:
        if remetente_id != usuario.id:
            ids.add(remetente_id)
        if destinatario_id != usuario.id:
            ids.add(destinatario_id)

    nao_lidas = {
        row["remetente_id"]: row["total"]
        for row in Mensagem.objects.filter(destinatario=usuario, lida=False)
        .values("remetente_id")
        .annotate(total=Count("id"))
    }

    contatos = User.objects.filter(id__in=ids, is_active=True).order_by("nome")
    data = ChatContatoSerializer(contatos, many=True).data
    for item in data:
        item["nao_lidas"] = nao_lidas.get(item["id"], 0)
    return Response(data)


@api_view(["GET", "POST", "PATCH"])
@permission_classes([IsMembroAtivo])
def chat_mensagens_usuario_view(request, usuario_id):
    destino = User.objects.filter(pk=usuario_id, is_active=True).first()
    if not destino:
        return Response({"detail": "Usuário não encontrado."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        mensagens = list(
            Mensagem.objects.filter(
                Q(remetente=request.user, destinatario=destino)
                | Q(remetente=destino, destinatario=request.user)
            )
            .order_by("-id")[:200]
        )
        mensagens.reverse()
        return Response(ChatMensagemSerializer(mensagens, many=True).data)

    if request.method == "POST":
        texto = (request.data.get("mensagem") or "").strip()
        if not texto:
            return Response({"detail": "Mensagem obrigatória."}, status=status.HTTP_400_BAD_REQUEST)
        if len(texto) > MAX_CHAT_MENSAGEM_CHARS:
            return Response(
                {"detail": f"Mensagem excede {MAX_CHAT_MENSAGEM_CHARS} caracteres."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        msg = Mensagem.objects.create(remetente=request.user, destinatario=destino, mensagem=texto)
        return Response(ChatMensagemSerializer(msg).data, status=status.HTTP_201_CREATED)

    updated = Mensagem.objects.filter(remetente=destino, destinatario=request.user, lida=False).update(lida=True)
    return Response({"updated": updated}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsMembroAtivo])
def chat_ping_view(request):
    nao_lidas = Mensagem.objects.filter(destinatario=request.user, lida=False).count()
    return Response({"nao_lidas": nao_lidas}, status=status.HTTP_200_OK)


@api_view(["POST", "DELETE"])
@permission_classes([IsMembroAtivo])
def push_dispositivo_view(request):
    if request.method == "POST":
        serializer = DispositivoFCMSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]
        plataforma = serializer.validated_data["plataforma"]
        dispositivo, _ = DispositivoFCM.objects.update_or_create(
            token=token,
            defaults={
                "usuario": request.user,
                "plataforma": plataforma,
                "ativo": True,
            },
        )
        return Response(
            {
                "token": dispositivo.token,
                "plataforma": dispositivo.plataforma,
                "ativo": dispositivo.ativo,
            },
            status=status.HTTP_200_OK,
        )

    token = request.data.get("token")
    if not token:
        DispositivoFCM.objects.filter(usuario=request.user, ativo=True).update(ativo=False)
        return Response(status=status.HTTP_204_NO_CONTENT)

    DispositivoFCM.objects.filter(usuario=request.user, token=token).update(ativo=False)
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Views Admin ───────────────────────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([IsAdminIgreja])
def admin_dashboard_view(request):
    now = timezone.now()
    mes, ano = now.month, now.year

    total_membros = Membro.objects.filter(status=StatusMembro.ATIVO).count()

    visitantes_mes = Visitante.objects.filter(
        data_ultima_visita__month=mes,
        data_ultima_visita__year=ano,
    ).count()

    eventos_futuros = Evento.objects.filter(
        data_inicio__gte=now,
        status__in=[StatusEvento.PLANEJAMENTO, StatusEvento.ABERTO],
    ).count()

    from django.db.models import Case, DecimalField, When
    financeiro = LancamentoFinanceiro.objects.filter(
        data_lancamento__month=mes,
        data_lancamento__year=ano,
    ).aggregate(
        entradas=Sum(
            Case(
                When(
                    tipo__in=[TipoLancamento.DIZIMO, TipoLancamento.OFERTA, TipoLancamento.DOACAO],
                    then="valor",
                ),
                default=None,
                output_field=DecimalField(),
            )
        ),
        saidas=Sum(
            Case(
                When(tipo=TipoLancamento.SAIDA, then="valor"),
                default=None,
                output_field=DecimalField(),
            )
        ),
    )
    entradas = financeiro["entradas"] or 0
    saidas = financeiro["saidas"] or 0

    return Response({
        "total_membros": total_membros,
        "visitantes_mes": visitantes_mes,
        "eventos_futuros": eventos_futuros,
        "entradas_mes": float(entradas),
        "saidas_mes": float(saidas),
        "saldo_mes": float(entradas - saidas),
    }, status=status.HTTP_200_OK)


@api_view(["GET", "POST"])
@permission_classes([IsAdminIgreja])
def admin_membros_view(request):
    if request.method == "GET":
        qs = Membro.objects.select_related("pessoa").order_by("pessoa__nome")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(AdminMembroListSerializer(page, many=True).data)

    # Criação de membro requer permissão mais restrita (apenas ADMIN e PASTOR)
    can_create = CanCreateMembers()
    if not can_create.has_permission(request, None):
        logger.warning(
            "Tentativa não autorizada de criar membro. Usuário: %s (nivel=%s)",
            request.user.email,
            getattr(request.user, "nivel_acesso", "?"),
        )
        return Response({"detail": can_create.message}, status=status.HTTP_403_FORBIDDEN)

    serializer = AdminMembroCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    with transaction.atomic():
        pessoa = Pessoa.objects.create(
            tipo=TipoPessoa.MEMBRO,
            nome=d["nome"],
            genero=d.get("genero", "Nao informado"),
            data_nascimento=d.get("data_nascimento"),
            telefone=d.get("telefone", ""),
            celular=d.get("celular", ""),
            email=d.get("email", ""),
            cidade=d.get("cidade", ""),
            estado=d.get("estado", ""),
            cadastrado_por=request.user,
        )
        membro = Membro.objects.create(
            pessoa=pessoa,
            cargo=d.get("cargo", ""),
            funcao=d.get("funcao", ""),
            status=d.get("status", StatusMembro.ATIVO),
            data_batismo=d.get("data_batismo"),
            data_conversao=d.get("data_conversao"),
            data_entrada=d.get("data_entrada"),
        )

    return Response(AdminMembroListSerializer(membro).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes([IsAdminIgreja])
def admin_membro_detail_view(request, membro_id):
    membro = Membro.objects.select_related("pessoa").filter(pk=membro_id).first()
    if not membro:
        return Response({"detail": "Membro não encontrado."}, status=status.HTTP_404_NOT_FOUND)

    serializer = AdminMembroPatchSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    pessoa_fields = ["nome", "telefone", "celular", "email", "cidade", "estado"]
    membro_fields = ["cargo", "funcao", "status", "data_batismo", "data_conversao", "data_entrada"]

    with transaction.atomic():
        pessoa = membro.pessoa
        pessoa_updated = False
        for field in pessoa_fields:
            if field in d:
                setattr(pessoa, field, d[field])
                pessoa_updated = True
        if pessoa_updated:
            pessoa.save()

        membro_updated = False
        for field in membro_fields:
            if field in d:
                setattr(membro, field, d[field])
                membro_updated = True
        if membro_updated:
            membro.save()

    return Response(AdminMembroListSerializer(membro).data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAdminIgreja])
def admin_visitantes_view(request):
    qs = Visitante.objects.select_related("pessoa").order_by("-data_ultima_visita")
    paginator = DefaultPagination()
    page = paginator.paginate_queryset(qs, request)
    return paginator.get_paginated_response(AdminVisitanteSerializer(page, many=True).data)


@api_view(["GET"])
@permission_classes([IsAdminIgreja])
def admin_evento_inscricoes_view(request, evento_id):
    evento = Evento.objects.filter(pk=evento_id).first()
    if not evento:
        return Response({"detail": "Evento não encontrado."}, status=status.HTTP_404_NOT_FOUND)
    qs = EventoInscricao.objects.filter(evento=evento).select_related("pessoa").order_by("pessoa__nome")
    paginator = DefaultPagination()
    page = paginator.paginate_queryset(qs, request)
    return paginator.get_paginated_response(EventoInscricaoAdminSerializer(page, many=True).data)


@api_view(["GET", "POST"])
@permission_classes([IsFinanceiroIgreja])
def admin_financeiro_lancamentos_view(request):
    if request.method == "GET":
        qs = (
            LancamentoFinanceiro.objects
            .select_related("categoria", "pessoa")
            .order_by("-data_lancamento", "-pk")
        )
        tipo = request.query_params.get("tipo")
        if tipo:
            qs = qs.filter(tipo=tipo)
        mes = request.query_params.get("mes")
        if mes:
            qs = qs.filter(data_lancamento__month=mes)
        ano = request.query_params.get("ano")
        if ano:
            qs = qs.filter(data_lancamento__year=ano)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(LancamentoFinanceiroSerializer(page, many=True).data)

    serializer = LancamentoFinanceiroSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    lancamento = serializer.save(usuario=request.user)
    return Response(LancamentoFinanceiroSerializer(lancamento).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAdminIgreja])
def admin_relatorio_membros_view(request):
    total = Membro.objects.count()
    ativos = Membro.objects.filter(status=StatusMembro.ATIVO).count()
    por_status = list(
        Membro.objects.values("status").annotate(total=Count("id")).order_by("-total")
    )
    por_genero = list(
        Membro.objects.select_related("pessoa")
        .values("pessoa__genero")
        .annotate(total=Count("id"))
        .order_by("-total")
    )
    return Response({
        "total": total,
        "ativos": ativos,
        "por_status": por_status,
        "por_genero": [
            {"genero": r["pessoa__genero"], "total": r["total"]}
            for r in por_genero
        ],
    }, status=status.HTTP_200_OK)


@api_view(["GET", "PATCH"])
@permission_classes([IsAdminIgreja])
def configuracoes_igreja_view(request):
    config = ConfiguracaoIgreja.objects.first()

    if request.method == "GET":
        if not config:
            return Response({}, status=status.HTTP_200_OK)
        return Response(ConfiguracaoIgrejaSerializer(config).data)

    if not config:
        serializer = ConfiguracaoIgrejaSerializer(data=request.data)
    else:
        serializer = ConfiguracaoIgrejaSerializer(config, data=request.data, partial=True)

    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data, status=status.HTTP_200_OK)
