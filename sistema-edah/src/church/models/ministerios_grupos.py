from django.db import models

from .cadastros import Lider, Pessoa


class StatusAtivo(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    INATIVO = "inativo", "Inativo"


class Ministerio(models.Model):
    nome = models.CharField(max_length=200)
    descricao = models.TextField(blank=True, null=True)
    lider = models.ForeignKey(
        Lider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ministerios_lider",
        db_column="lider_id",
    )
    vice_lider = models.ForeignKey(
        Lider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ministerios_vice",
        db_column="vice_lider_id",
    )
    data_criacao = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=10,
        choices=StatusAtivo.choices,
        default=StatusAtivo.ATIVO,
    )

    class Meta:
        db_table = "ministerios"
        verbose_name_plural = "ministérios"

    def __str__(self):
        return self.nome


class MinisterioMembro(models.Model):
    ministerio = models.ForeignKey(
        Ministerio,
        on_delete=models.CASCADE,
        related_name="membros_vinculos",
        db_column="ministerio_id",
    )
    pessoa = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="ministerios_participacoes",
        db_column="pessoa_id",
    )
    funcao = models.CharField(max_length=100, blank=True, null=True)
    data_entrada = models.DateField(blank=True, null=True)
    data_saida = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=10,
        choices=StatusAtivo.choices,
        default=StatusAtivo.ATIVO,
    )

    class Meta:
        db_table = "ministerio_membros"


class DiaSemana(models.TextChoices):
    SEGUNDA = "Segunda", "Segunda"
    TERCA = "Terça", "Terça"
    QUARTA = "Quarta", "Quarta"
    QUINTA = "Quinta", "Quinta"
    SEXTA = "Sexta", "Sexta"
    SABADO = "Sábado", "Sábado"
    DOMINGO = "Domingo", "Domingo"


class PequenoGrupo(models.Model):
    nome = models.CharField(max_length=200)
    descricao = models.TextField(blank=True, null=True)
    lider = models.ForeignKey(
        Pessoa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pequenos_grupos_lider",
        db_column="lider_id",
    )
    vice_lider = models.ForeignKey(
        Pessoa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pequenos_grupos_vice",
        db_column="vice_lider_id",
    )
    anfitriao = models.ForeignKey(
        Pessoa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pequenos_grupos_anfitriao",
        db_column="anfitriao_id",
    )
    dia_reuniao = models.CharField(
        max_length=10,
        choices=DiaSemana.choices,
        blank=True,
        null=True,
    )
    horario_reuniao = models.TimeField(blank=True, null=True)
    endereco = models.CharField(max_length=255, blank=True, null=True)
    cidade = models.CharField(max_length=100, blank=True, null=True)
    bairro = models.CharField(max_length=100, blank=True, null=True)
    latitude = models.DecimalField(
        max_digits=10, decimal_places=8, blank=True, null=True
    )
    longitude = models.DecimalField(
        max_digits=11, decimal_places=8, blank=True, null=True
    )
    data_criacao = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=10,
        choices=StatusAtivo.choices,
        default=StatusAtivo.ATIVO,
    )

    class Meta:
        db_table = "pequenos_grupos"

    def __str__(self):
        return self.nome


class PequenoGrupoMembro(models.Model):
    grupo = models.ForeignKey(
        PequenoGrupo,
        on_delete=models.CASCADE,
        related_name="membros",
        db_column="grupo_id",
    )
    pessoa = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="pequenos_grupos_vinculos",
        db_column="pessoa_id",
    )
    data_entrada = models.DateField(blank=True, null=True)
    data_saida = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=10,
        choices=StatusAtivo.choices,
        default=StatusAtivo.ATIVO,
    )

    class Meta:
        db_table = "pequeno_grupo_membros"
