from django.db.models import Count
from rest_framework import serializers

from church.models import (
    CategoriaFinanceira,
    ClasseAluno,
    ClasseEstudo,
    ConfiguracaoIgreja,
    Curso,
    CursoAula,
    CursoMatricula,
    CursoModulo,
    CursoNota,
    CursoPresenca,
    Discipulado,
    DispositivoFCM,
    Evento,
    EventoInscricao,
    Familia,
    FamiliaMembro,
    Galeria,
    GaleriaFoto,
    LancamentoFinanceiro,
    Mensagem,
    Ministerio,
    MinisterioMembro,
    Membro,
    Noticia,
    PedidoOracao,
    Pessoa,
    PequenoGrupo,
    PequenoGrupoMembro,
    StatusEvento,
    StatusMembro,
    StatusNoticia,
    User,
    Visitante,
)


class UsuarioResumoSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "nome", "email", "nivel_acesso"]


class MembroMePessoaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pessoa
        fields = [
            "id",
            "nome",
            "genero",
            "data_nascimento",
            "telefone",
            "celular",
            "email",
            "cidade",
            "estado",
            "foto",
        ]


class MembroMeMembroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membro
        fields = [
            "data_batismo",
            "data_conversao",
            "data_entrada",
            "cargo",
            "funcao",
            "status",
        ]


class MembroMeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pessoa
        fields = ["telefone", "celular", "foto"]


class EventoListSerializer(serializers.ModelSerializer):
    vagas_restantes = serializers.SerializerMethodField()
    inscrito = serializers.SerializerMethodField()

    class Meta:
        model = Evento
        fields = [
            "id",
            "nome",
            "descricao",
            "tipo_evento",
            "data_inicio",
            "data_fim",
            "local",
            "capacidade_maxima",
            "valor_inscricao",
            "imagem_capa",
            "status",
            "vagas_restantes",
            "inscrito",
        ]

    def get_vagas_restantes(self, obj):
        if not obj.capacidade_maxima:
            return None
        inscritos = obj.inscricoes.count()
        return max(0, obj.capacidade_maxima - inscritos)

    def get_inscrito(self, obj):
        pessoa = self.context.get("pessoa")
        if not pessoa:
            return False
        return EventoInscricao.objects.filter(evento=obj, pessoa=pessoa).exists()


class NoticiaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Noticia
        fields = [
            "id",
            "titulo",
            "conteudo",
            "imagem",
            "data_publicacao",
            "status",
        ]


class GrupoResumoSerializer(serializers.ModelSerializer):
    lider = serializers.SerializerMethodField()
    vice_lider = serializers.SerializerMethodField()
    membros_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = PequenoGrupo
        fields = [
            "id",
            "nome",
            "descricao",
            "lider",
            "vice_lider",
            "dia_reuniao",
            "horario_reuniao",
            "membros_count",
        ]

    def get_lider(self, obj):
        return obj.lider.nome if obj.lider else None

    def get_vice_lider(self, obj):
        return obj.vice_lider.nome if obj.vice_lider else None


class GrupoDetalheSerializer(GrupoResumoSerializer):
    membros = serializers.SerializerMethodField()

    class Meta(GrupoResumoSerializer.Meta):
        fields = GrupoResumoSerializer.Meta.fields + ["membros"]

    def get_membros(self, obj):
        return [
            {
                "id": vinculo.pessoa_id,
                "nome": vinculo.pessoa.nome,
                "foto": vinculo.pessoa.foto,
                "status": vinculo.status,
            }
            for vinculo in obj.membros.select_related("pessoa").all()
        ]


class MinisterioResumoSerializer(serializers.ModelSerializer):
    lider = serializers.SerializerMethodField()
    vice_lider = serializers.SerializerMethodField()
    membros_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Ministerio
        fields = [
            "id",
            "nome",
            "descricao",
            "lider",
            "vice_lider",
            "status",
            "membros_count",
        ]

    def get_lider(self, obj):
        if not obj.lider:
            return None
        return obj.lider.pessoa.nome

    def get_vice_lider(self, obj):
        if not obj.vice_lider:
            return None
        return obj.vice_lider.pessoa.nome


class MinisterioDetalheSerializer(MinisterioResumoSerializer):
    membros = serializers.SerializerMethodField()

    class Meta(MinisterioResumoSerializer.Meta):
        fields = MinisterioResumoSerializer.Meta.fields + ["membros"]

    def get_membros(self, obj):
        return [
            {
                "id": vinculo.pessoa_id,
                "nome": vinculo.pessoa.nome,
                "funcao": vinculo.funcao,
                "status": vinculo.status,
            }
            for vinculo in obj.membros_vinculos.select_related("pessoa").all()
        ]


class CursoAulaSerializer(serializers.ModelSerializer):
    class Meta:
        model = CursoAula
        fields = ["id", "titulo", "conteudo", "material_apoio", "video_url", "ordem"]


class CursoModuloSerializer(serializers.ModelSerializer):
    aulas = CursoAulaSerializer(many=True, read_only=True)

    class Meta:
        model = CursoModulo
        fields = ["id", "nome", "descricao", "ordem", "media_aprovacao", "aulas"]


class CursoSerializer(serializers.ModelSerializer):
    instrutor = serializers.SerializerMethodField()
    modulos = CursoModuloSerializer(many=True, read_only=True)
    matriculado = serializers.SerializerMethodField()

    class Meta:
        model = Curso
        fields = [
            "id",
            "nome",
            "descricao",
            "instrutor",
            "carga_horaria",
            "data_inicio",
            "data_fim",
            "status",
            "matriculado",
            "modulos",
        ]

    def get_instrutor(self, obj):
        return obj.instrutor.nome if obj.instrutor else None

    def get_matriculado(self, obj):
        pessoa = self.context.get("pessoa")
        if not pessoa:
            return False
        return CursoMatricula.objects.filter(curso=obj, pessoa=pessoa).exists()


class CursoMatriculaSerializer(serializers.ModelSerializer):
    curso_nome = serializers.CharField(source="curso.nome", read_only=True)

    class Meta:
        model = CursoMatricula
        fields = [
            "id",
            "curso",
            "curso_nome",
            "data_matricula",
            "data_conclusao",
            "nota_final",
            "status",
        ]


class ClasseSerializer(serializers.ModelSerializer):
    professor = serializers.SerializerMethodField()

    class Meta:
        model = ClasseEstudo
        fields = [
            "id",
            "nome",
            "descricao",
            "professor",
            "dia_semana",
            "horario",
            "local",
            "status",
        ]

    def get_professor(self, obj):
        return obj.professor.nome if obj.professor else None


class DiscipuladoSerializer(serializers.ModelSerializer):
    discipulador_nome = serializers.CharField(source="discipulador.nome", read_only=True)
    discipulo_nome = serializers.CharField(source="discipulo.nome", read_only=True)

    class Meta:
        model = Discipulado
        fields = [
            "id",
            "discipulador",
            "discipulador_nome",
            "discipulo",
            "discipulo_nome",
            "data_inicio",
            "data_conclusao",
            "status",
            "observacoes",
        ]


class GaleriaSerializer(serializers.ModelSerializer):
    fotos_count = serializers.SerializerMethodField()

    def get_fotos_count(self, obj):
        # Usa anotação do queryset quando disponível; caso contrário faz contagem direta.
        annotated = getattr(obj, "fotos_count", None)
        if annotated is not None:
            return annotated
        return obj.fotos.count()

    class Meta:
        model = Galeria
        fields = ["id", "titulo", "descricao", "capa", "data_evento", "fotos_count"]


class GaleriaFotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = GaleriaFoto
        fields = ["id", "arquivo", "legenda", "ordem"]


class PedidoOracaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PedidoOracao
        fields = ["id", "pedido", "anonimo", "status", "data_pedido"]
        read_only_fields = ["status", "data_pedido"]


class DispositivoFCMSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispositivoFCM
        fields = ["token", "plataforma"]


class ChatContatoSerializer(serializers.ModelSerializer):
    nao_lidas = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "nome", "email", "nao_lidas"]


class ChatMensagemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mensagem
        fields = ["id", "remetente_id", "destinatario_id", "mensagem", "lida", "data_envio"]


def eventos_publicados_queryset():
    return (
        Evento.objects.filter(
            publicar_app=True,
            status__in=[StatusEvento.ABERTO, StatusEvento.PLANEJAMENTO],
        )
        .prefetch_related("inscricoes")
        .order_by("data_inicio")
    )


def noticias_publicadas_queryset():
    return Noticia.objects.filter(
        publicar_app=True,
        status=StatusNoticia.PUBLICADO,
    ).order_by("-data_publicacao", "-data_criacao")


def grupos_do_membro_queryset(pessoa):
    return (
        PequenoGrupo.objects.filter(membros__pessoa=pessoa)
        .annotate(membros_count=Count("membros"))
        .select_related("lider", "vice_lider")
        .prefetch_related("membros__pessoa")
        .distinct()
        .order_by("nome")
    )


def ministerios_do_membro_queryset(pessoa):
    return (
        Ministerio.objects.filter(membros_vinculos__pessoa=pessoa)
        .annotate(membros_count=Count("membros_vinculos"))
        .select_related("lider__pessoa", "vice_lider__pessoa")
        .prefetch_related("membros_vinculos__pessoa")
        .distinct()
        .order_by("nome")
    )


def galerias_publicadas_queryset():
    return Galeria.objects.filter(publicar_app=True).annotate(fotos_count=Count("fotos")).order_by("-id")


def familia_do_membro(pessoa):
    return (
        Familia.objects.filter(membros__pessoa=pessoa)
        .select_related("responsavel")
        .prefetch_related("membros__pessoa")
        .first()
    )


# ── Serializers Admin ─────────────────────────────────────────────────────────


class AdminMembroListSerializer(serializers.ModelSerializer):
    nome = serializers.CharField(source="pessoa.nome")
    email = serializers.EmailField(source="pessoa.email")
    telefone = serializers.CharField(source="pessoa.telefone")
    celular = serializers.CharField(source="pessoa.celular")
    foto = serializers.CharField(source="pessoa.foto")
    genero = serializers.CharField(source="pessoa.genero")
    data_nascimento = serializers.DateField(source="pessoa.data_nascimento")
    cidade = serializers.CharField(source="pessoa.cidade")
    estado = serializers.CharField(source="pessoa.estado")

    class Meta:
        model = Membro
        fields = [
            "id", "nome", "email", "telefone", "celular", "foto",
            "genero", "data_nascimento", "cidade", "estado",
            "cargo", "funcao", "status",
            "data_batismo", "data_conversao", "data_entrada",
        ]


class AdminMembroCreateSerializer(serializers.Serializer):
    # Campos de Pessoa
    nome = serializers.CharField(max_length=200)
    genero = serializers.ChoiceField(
        choices=Pessoa._meta.get_field("genero").choices,
        required=False,
    )
    data_nascimento = serializers.DateField(required=False, allow_null=True)
    telefone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    celular = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    cidade = serializers.CharField(max_length=100, required=False, allow_blank=True)
    estado = serializers.CharField(max_length=2, required=False, allow_blank=True)
    # Campos de Membro
    cargo = serializers.CharField(max_length=100, required=False, allow_blank=True)
    funcao = serializers.CharField(max_length=100, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=StatusMembro.choices, required=False)
    data_batismo = serializers.DateField(required=False, allow_null=True)
    data_conversao = serializers.DateField(required=False, allow_null=True)
    data_entrada = serializers.DateField(required=False, allow_null=True)


class AdminMembroPatchSerializer(serializers.Serializer):
    nome = serializers.CharField(max_length=200, required=False)
    telefone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    celular = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    cidade = serializers.CharField(max_length=100, required=False, allow_blank=True)
    estado = serializers.CharField(max_length=2, required=False, allow_blank=True)
    cargo = serializers.CharField(max_length=100, required=False, allow_blank=True)
    funcao = serializers.CharField(max_length=100, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=StatusMembro.choices, required=False)
    data_batismo = serializers.DateField(required=False, allow_null=True)
    data_conversao = serializers.DateField(required=False, allow_null=True)
    data_entrada = serializers.DateField(required=False, allow_null=True)


class AdminVisitanteSerializer(serializers.ModelSerializer):
    nome = serializers.CharField(source="pessoa.nome")
    email = serializers.EmailField(source="pessoa.email")
    telefone = serializers.CharField(source="pessoa.telefone")
    genero = serializers.CharField(source="pessoa.genero")
    cidade = serializers.CharField(source="pessoa.cidade")

    class Meta:
        model = Visitante
        fields = [
            "id", "nome", "email", "telefone", "genero", "cidade",
            "data_primeira_visita", "data_ultima_visita",
            "total_visitas", "convertido_membro",
        ]


class LancamentoFinanceiroSerializer(serializers.ModelSerializer):
    pessoa_nome = serializers.CharField(source="pessoa.nome", read_only=True, default=None)
    categoria_nome = serializers.CharField(source="categoria.nome", read_only=True, default=None)

    class Meta:
        model = LancamentoFinanceiro
        fields = [
            "id", "tipo", "categoria", "categoria_nome",
            "pessoa", "pessoa_nome",
            "valor", "data_lancamento", "descricao",
            "metodo_pagamento", "comprovante",
        ]
        read_only_fields = ["id"]


class ConfiguracaoIgrejaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfiguracaoIgreja
        fields = [
            "id", "nome_exibicao", "cnpj", "endereco",
            "cidade", "estado", "cep", "telefone",
            "email", "site", "pastor_presidente",
            "data_fundacao", "logo",
        ]


class EventoInscricaoAdminSerializer(serializers.ModelSerializer):
    nome = serializers.CharField(source="pessoa.nome", read_only=True)
    email = serializers.EmailField(source="pessoa.email", read_only=True)
    telefone = serializers.CharField(source="pessoa.telefone", read_only=True)

    class Meta:
        model = EventoInscricao
        fields = ["id", "nome", "email", "telefone", "data_inscricao", "pago", "valor_pago"]
