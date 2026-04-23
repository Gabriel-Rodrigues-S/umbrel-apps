from django.db import models

from .cadastros import Pessoa


class StatusCurso(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    CONCLUIDO = "concluido", "Concluído"
    CANCELADO = "cancelado", "Cancelado"


class Curso(models.Model):
    nome = models.CharField(max_length=200)
    descricao = models.TextField(blank=True, null=True)
    instrutor = models.ForeignKey(
        Pessoa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cursos_instruidos",
        db_column="instrutor_id",
    )
    carga_horaria = models.PositiveIntegerField(blank=True, null=True)
    data_inicio = models.DateField(blank=True, null=True)
    data_fim = models.DateField(blank=True, null=True)
    certificado_template = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=StatusCurso.choices,
        default=StatusCurso.ATIVO,
    )

    class Meta:
        db_table = "cursos"

    def __str__(self):
        return self.nome


class CursoModulo(models.Model):
    curso = models.ForeignKey(
        Curso,
        on_delete=models.CASCADE,
        related_name="modulos",
        db_column="curso_id",
    )
    nome = models.CharField(max_length=200)
    descricao = models.TextField(blank=True, null=True)
    ordem = models.PositiveIntegerField(default=1)
    media_aprovacao = models.DecimalField(
        max_digits=5, decimal_places=2, default=7.00
    )

    class Meta:
        db_table = "curso_modulos"
        ordering = ["ordem"]


class CursoAula(models.Model):
    modulo = models.ForeignKey(
        CursoModulo,
        on_delete=models.CASCADE,
        related_name="aulas",
        db_column="modulo_id",
    )
    titulo = models.CharField(max_length=200)
    conteudo = models.TextField(blank=True, null=True)
    material_apoio = models.CharField(max_length=255, blank=True, null=True)
    video_url = models.CharField(max_length=255, blank=True, null=True)
    ordem = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "curso_aulas"
        ordering = ["ordem"]


class StatusMatricula(models.TextChoices):
    MATRICULADO = "matriculado", "Matriculado"
    CURSANDO = "cursando", "Cursando"
    APROVADO = "aprovado", "Aprovado"
    REPROVADO = "reprovado", "Reprovado"
    CANCELADO = "cancelado", "Cancelado"


class CursoMatricula(models.Model):
    curso = models.ForeignKey(
        Curso,
        on_delete=models.CASCADE,
        related_name="matriculas",
        db_column="curso_id",
    )
    pessoa = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="curso_matriculas",
        db_column="pessoa_id",
    )
    data_matricula = models.DateField(blank=True, null=True)
    data_conclusao = models.DateField(blank=True, null=True)
    nota_final = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    status = models.CharField(
        max_length=20,
        choices=StatusMatricula.choices,
        default=StatusMatricula.MATRICULADO,
    )

    class Meta:
        db_table = "curso_matriculas"


class CursoPresenca(models.Model):
    aula = models.ForeignKey(
        CursoAula,
        on_delete=models.CASCADE,
        related_name="presencas",
        db_column="aula_id",
    )
    matricula = models.ForeignKey(
        CursoMatricula,
        on_delete=models.CASCADE,
        related_name="presencas",
        db_column="matricula_id",
    )
    data_aula = models.DateField()
    presente = models.BooleanField(default=False)

    class Meta:
        db_table = "curso_presencas"


class CursoNota(models.Model):
    modulo = models.ForeignKey(
        CursoModulo,
        on_delete=models.CASCADE,
        related_name="notas",
        db_column="modulo_id",
    )
    matricula = models.ForeignKey(
        CursoMatricula,
        on_delete=models.CASCADE,
        related_name="notas_modulos",
        db_column="matricula_id",
    )
    nota = models.DecimalField(max_digits=5, decimal_places=2)
    data_avaliacao = models.DateField(blank=True, null=True)

    class Meta:
        db_table = "curso_notas"


class Certificado(models.Model):
    matricula = models.ForeignKey(
        CursoMatricula,
        on_delete=models.CASCADE,
        related_name="certificados",
        db_column="matricula_id",
    )
    codigo_verificacao = models.CharField(max_length=100, unique=True)
    data_emissao = models.DateField()
    arquivo_pdf = models.CharField(max_length=255, blank=True, null=True)
    enviado_email = models.BooleanField(default=False)
    data_envio_email = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "certificados"
