from django.db import models

from .cadastros import Pessoa
from .ministerios_grupos import DiaSemana


class StatusDiscipulado(models.TextChoices):
    EM_ANDAMENTO = "em_andamento", "Em andamento"
    CONCLUIDO = "concluido", "Concluído"
    CANCELADO = "cancelado", "Cancelado"


class Discipulado(models.Model):
    discipulador = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="discipulados_como_discipulador",
        db_column="discipulador_id",
    )
    discipulo = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="discipulados_como_discipulo",
        db_column="discipulo_id",
    )
    data_inicio = models.DateField(blank=True, null=True)
    data_conclusao = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=StatusDiscipulado.choices,
        default=StatusDiscipulado.EM_ANDAMENTO,
    )
    observacoes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "discipulado"


class StatusClasseEstudo(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    CONCLUIDO = "concluido", "Concluído"
    CANCELADO = "cancelado", "Cancelado"


class ClasseEstudo(models.Model):
    nome = models.CharField(max_length=200)
    descricao = models.TextField(blank=True, null=True)
    professor = models.ForeignKey(
        Pessoa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classes_ensinadas",
        db_column="professor_id",
    )
    dia_semana = models.CharField(
        max_length=10,
        choices=DiaSemana.choices,
        blank=True,
        null=True,
    )
    horario = models.TimeField(blank=True, null=True)
    local = models.CharField(max_length=255, blank=True, null=True)
    data_inicio = models.DateField(blank=True, null=True)
    data_fim = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=StatusClasseEstudo.choices,
        default=StatusClasseEstudo.ATIVO,
    )

    class Meta:
        db_table = "classes_estudo"
        verbose_name_plural = "classes de estudo"

    def __str__(self):
        return self.nome


class StatusClasseAluno(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    CONCLUIDO = "concluido", "Concluído"
    DESISTENTE = "desistente", "Desistente"


class ClasseAluno(models.Model):
    classe = models.ForeignKey(
        ClasseEstudo,
        on_delete=models.CASCADE,
        related_name="alunos",
        db_column="classe_id",
    )
    pessoa = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="classes_inscricoes",
        db_column="pessoa_id",
    )
    data_inscricao = models.DateField(blank=True, null=True)
    data_conclusao = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=StatusClasseAluno.choices,
        default=StatusClasseAluno.ATIVO,
    )

    class Meta:
        db_table = "classe_alunos"
