from django.conf import settings
from django.db import models

from .cadastros import Pessoa


class TipoEvento(models.TextChoices):
    CULTO = "culto", "Culto"
    CONFERENCIA = "conferencia", "Conferência"
    RETIRO = "retiro", "Retiro"
    CASAMENTO = "casamento", "Casamento"
    BATISMO = "batismo", "Batismo"
    REUNIAO = "reuniao", "Reunião"
    OUTRO = "outro", "Outro"


class StatusEvento(models.TextChoices):
    PLANEJAMENTO = "planejamento", "Planejamento"
    ABERTO = "aberto", "Aberto"
    ENCERRADO = "encerrado", "Encerrado"
    CANCELADO = "cancelado", "Cancelado"


class Evento(models.Model):
    nome = models.CharField(max_length=200)
    descricao = models.TextField(blank=True, null=True)
    tipo_evento = models.CharField(max_length=20, choices=TipoEvento.choices)
    data_inicio = models.DateTimeField()
    data_fim = models.DateTimeField(blank=True, null=True)
    local = models.CharField(max_length=255, blank=True, null=True)
    capacidade_maxima = models.PositiveIntegerField(blank=True, null=True)
    valor_inscricao = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    imagem_capa = models.CharField(max_length=255, blank=True, null=True)
    publicar_site = models.BooleanField(default=False)
    publicar_app = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=StatusEvento.choices,
        default=StatusEvento.PLANEJAMENTO,
    )
    data_criacao = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventos_criados",
    )

    class Meta:
        db_table = "eventos"
        indexes = [
            models.Index(fields=["data_inicio"]),
        ]

    def __str__(self):
        return self.nome


class EventoResponsavel(models.Model):
    evento = models.ForeignKey(
        Evento,
        on_delete=models.CASCADE,
        related_name="responsaveis",
        db_column="evento_id",
    )
    pessoa = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="eventos_responsabilidades",
        db_column="pessoa_id",
    )
    funcao = models.CharField(max_length=100)
    permissoes = models.JSONField(blank=True, null=True)

    class Meta:
        db_table = "evento_responsaveis"


class EventoInscricao(models.Model):
    evento = models.ForeignKey(
        Evento,
        on_delete=models.CASCADE,
        related_name="inscricoes",
        db_column="evento_id",
    )
    pessoa = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="evento_inscricoes",
        db_column="pessoa_id",
    )
    data_inscricao = models.DateTimeField(auto_now_add=True)
    valor_pago = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    pago = models.BooleanField(default=False)
    presente = models.BooleanField(default=False)
    observacoes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "evento_inscricoes"
