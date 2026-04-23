from django.conf import settings
from django.db import models

from .cadastros import Pessoa
from .eventos import Evento


class StatusNoticia(models.TextChoices):
    RASCUNHO = "rascunho", "Rascunho"
    PUBLICADO = "publicado", "Publicado"
    ARQUIVADO = "arquivado", "Arquivado"


class Noticia(models.Model):
    titulo = models.CharField(max_length=255)
    conteudo = models.TextField()
    imagem = models.CharField(max_length=255, blank=True, null=True)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="noticias",
        db_column="autor_id",
    )
    data_publicacao = models.DateTimeField(blank=True, null=True)
    publicar_site = models.BooleanField(default=False)
    publicar_app = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=StatusNoticia.choices,
        default=StatusNoticia.RASCUNHO,
    )
    data_criacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "noticias"
        verbose_name_plural = "notícias"

    def __str__(self):
        return self.titulo


class StatusPedidoOracao(models.TextChoices):
    PENDENTE = "pendente", "Pendente"
    ORANDO = "orando", "Orando"
    RESPONDIDO = "respondido", "Respondido"
    ARQUIVADO = "arquivado", "Arquivado"


class PedidoOracao(models.Model):
    pessoa = models.ForeignKey(
        Pessoa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pedidos_oracao",
        db_column="pessoa_id",
    )
    nome = models.CharField(max_length=200, blank=True, null=True)
    email = models.CharField(max_length=150, blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    pedido = models.TextField()
    anonimo = models.BooleanField(default=False)
    data_pedido = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=StatusPedidoOracao.choices,
        default=StatusPedidoOracao.PENDENTE,
    )

    class Meta:
        db_table = "pedidos_oracao"
        verbose_name_plural = "pedidos de oração"


class Galeria(models.Model):
    titulo = models.CharField(max_length=200)
    descricao = models.TextField(blank=True, null=True)
    evento = models.ForeignKey(
        Evento,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="galerias",
        db_column="evento_id",
    )
    data_evento = models.DateField(blank=True, null=True)
    capa = models.CharField(max_length=255, blank=True, null=True)
    publicar_app = models.BooleanField(default=False)
    data_criacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "galeria"
        verbose_name_plural = "galerias"

    def __str__(self):
        return self.titulo


class GaleriaFoto(models.Model):
    galeria = models.ForeignKey(
        Galeria,
        on_delete=models.CASCADE,
        related_name="fotos",
        db_column="galeria_id",
    )
    arquivo = models.CharField(max_length=255)
    legenda = models.CharField(max_length=255, blank=True, null=True)
    ordem = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "galeria_fotos"


class Mensagem(models.Model):
    remetente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mensagens_enviadas",
        db_column="remetente_id",
    )
    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mensagens_recebidas",
        db_column="destinatario_id",
    )
    assunto = models.CharField(max_length=255, blank=True, null=True)
    mensagem = models.TextField()
    lida = models.BooleanField(default=False)
    data_leitura = models.DateTimeField(blank=True, null=True)
    data_envio = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mensagens"
        indexes = [
            models.Index(fields=["destinatario", "lida"], name="msg_dest_lida_idx"),
        ]
