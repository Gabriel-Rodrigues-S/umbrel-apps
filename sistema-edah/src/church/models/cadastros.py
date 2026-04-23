import secrets
import string

from django.conf import settings
from django.db import models, transaction


def _gerar_codigo_acesso():
    alfabeto = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(6))


class Igreja(models.Model):
    nome = models.CharField(max_length=200)
    cnpj = models.CharField(max_length=18, blank=True, null=True)
    endereco = models.TextField(blank=True, null=True)
    bairro = models.CharField(max_length=100, blank=True, null=True)
    cidade = models.CharField(max_length=100, blank=True, null=True)
    estado = models.CharField(max_length=2, blank=True, null=True)
    cep = models.CharField(max_length=10, blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(max_length=150, blank=True, null=True)
    site = models.CharField(max_length=200, blank=True, null=True)
    pastor_presidente = models.CharField(max_length=200, blank=True, null=True)
    data_fundacao = models.DateField(blank=True, null=True)
    logo = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "igreja"
        verbose_name = "igreja"
        verbose_name_plural = "igreja"

    def __str__(self):
        return self.nome


class TipoPessoa(models.TextChoices):
    MEMBRO = "membro", "Membro"
    VISITANTE = "visitante", "Visitante"
    CONGREGADO = "congregado", "Congregado"


class Genero(models.TextChoices):
    MASCULINO = "Masculino", "Masculino"
    FEMININO = "Feminino", "Feminino"
    NAO_INFORMADO = "Nao informado", "Não informado"


class EstadoCivil(models.TextChoices):
    CASADO = "Casado(a)", "Casado(a)"
    CONVIVENTE = "Convivente", "Convivente"
    SOLTEIRO = "Solteiro(a)", "Solteiro(a)"
    DIVORCIADO = "Divorciado(a)", "Divorciado(a)"
    VIUVO = "Viuvo(a)", "Viúvo(a)"


class Pessoa(models.Model):
    tipo = models.CharField(max_length=20, choices=TipoPessoa.choices)
    nome = models.CharField(max_length=200)
    genero = models.CharField(
        max_length=20,
        choices=Genero.choices,
        default=Genero.NAO_INFORMADO,
    )
    data_nascimento = models.DateField(blank=True, null=True)
    profissao = models.CharField(max_length=150, blank=True, null=True)
    estado_civil = models.CharField(
        max_length=20,
        choices=EstadoCivil.choices,
        blank=True,
        null=True,
    )
    telefone = models.CharField(max_length=20, blank=True, null=True)
    celular = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(max_length=150, blank=True, null=True, db_index=True)
    cep = models.CharField(max_length=10, blank=True, null=True)
    endereco = models.CharField(max_length=255, blank=True, null=True)
    numero = models.CharField(max_length=20, blank=True, null=True)
    complemento = models.CharField(max_length=100, blank=True, null=True)
    bairro = models.CharField(max_length=100, blank=True, null=True)
    cidade = models.CharField(max_length=100, blank=True, null=True)
    estado = models.CharField(max_length=2, blank=True, null=True)
    latitude = models.DecimalField(
        max_digits=10, decimal_places=8, blank=True, null=True
    )
    longitude = models.DecimalField(
        max_digits=11, decimal_places=8, blank=True, null=True
    )
    como_conheceu_igreja = models.TextField(blank=True, null=True)
    foto = models.CharField(max_length=255, blank=True, null=True)
    observacoes = models.TextField(blank=True, null=True)
    status_personalizado = models.CharField(max_length=100, blank=True, null=True)
    data_cadastro = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)
    cadastrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pessoas_cadastradas",
    )

    class Meta:
        db_table = "pessoas"
        indexes = [
            models.Index(fields=["tipo"]),
            models.Index(fields=["nome"]),
            models.Index(fields=["status_personalizado"]),
        ]

    def __str__(self):
        return self.nome


class StatusMembro(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    INATIVO = "inativo", "Inativo"
    TRANSFERIDO = "transferido", "Transferido"
    DISCIPLINADO = "disciplinado", "Disciplinado"
    FALECIDO = "falecido", "Falecido"


class Membro(models.Model):
    pessoa = models.OneToOneField(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="membro",
        db_column="pessoa_id",
    )
    data_batismo = models.DateField(blank=True, null=True)
    data_conversao = models.DateField(blank=True, null=True)
    data_entrada = models.DateField(blank=True, null=True)
    cargo = models.CharField(max_length=100, blank=True, null=True)
    funcao = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=StatusMembro.choices,
        default=StatusMembro.ATIVO,
    )
    codigo_acesso = models.CharField(
        max_length=6,
        unique=True,
        blank=True,
        editable=False,
        help_text="Código de acesso ao app mobile (gerado automaticamente)",
    )

    class Meta:
        db_table = "membros"

    def save(self, *args, **kwargs):
        if not self.codigo_acesso:
            from django.db import IntegrityError
            # Usa savepoint atômico por tentativa para evitar que um IntegrityError
            # aborte a transação externa em casos de concorrência.
            for _ in range(10):
                self.codigo_acesso = _gerar_codigo_acesso()
                try:
                    with transaction.atomic():
                        super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    self.codigo_acesso = ""
                    continue
            raise RuntimeError(
                "Não foi possível gerar um código de acesso único após 10 tentativas."
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Membro: {self.pessoa.nome}"


class Visitante(models.Model):
    pessoa = models.OneToOneField(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="visitante",
        db_column="pessoa_id",
    )
    data_primeira_visita = models.DateField(blank=True, null=True)
    data_ultima_visita = models.DateField(blank=True, null=True)
    total_visitas = models.PositiveIntegerField(default=1)
    convertido_membro = models.BooleanField(default=False)
    data_conversao_membro = models.DateField(blank=True, null=True)

    class Meta:
        db_table = "visitantes"

    def __str__(self):
        return f"Visitante: {self.pessoa.nome}"


class Familia(models.Model):
    nome_familia = models.CharField(max_length=200)
    responsavel = models.ForeignKey(
        Pessoa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="familias_responsavel",
        db_column="responsavel_id",
    )
    data_criacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "familias"
        verbose_name_plural = "famílias"

    def __str__(self):
        return self.nome_familia


class Parentesco(models.TextChoices):
    PAI = "Pai", "Pai"
    MAE = "Mãe", "Mãe"
    FILHO = "Filho(a)", "Filho(a)"
    CONJUGE = "Cônjuge", "Cônjuge"
    OUTRO = "Outro", "Outro"


class FamiliaMembro(models.Model):
    familia = models.ForeignKey(
        Familia,
        on_delete=models.CASCADE,
        related_name="membros",
        db_column="familia_id",
    )
    pessoa = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="familias_vinculos",
        db_column="pessoa_id",
    )
    parentesco = models.CharField(max_length=20, choices=Parentesco.choices)

    class Meta:
        db_table = "familia_membros"
        constraints = [
            models.UniqueConstraint(
                fields=["familia", "pessoa"],
                name="uniq_familia_membro_pessoa",
            ),
        ]


class Casal(models.Model):
    esposo = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="casais_como_esposo",
        db_column="esposo_id",
    )
    esposa = models.ForeignKey(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="casais_como_esposa",
        db_column="esposa_id",
    )
    data_casamento = models.DateField(blank=True, null=True)
    familia = models.ForeignKey(
        Familia,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="casais",
        db_column="familia_id",
    )

    class Meta:
        db_table = "casais"


class TipoLideranca(models.TextChoices):
    PASTOR = "pastor", "Pastor"
    PRESBITERO = "presbitero", "Presbítero"
    DIACONO = "diacono", "Diácono"
    LIDER_MINISTERIO = "lider_ministerio", "Líder de ministério"
    LIDER_GRUPO = "lider_grupo", "Líder de grupo"
    OUTRO = "outro", "Outro"


class StatusLider(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    INATIVO = "inativo", "Inativo"
    LICENCIADO = "licenciado", "Licenciado"


class Lider(models.Model):
    pessoa = models.OneToOneField(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="lider",
        db_column="pessoa_id",
    )
    tipo_lideranca = models.CharField(max_length=30, choices=TipoLideranca.choices)
    data_inicio = models.DateField(blank=True, null=True)
    data_fim = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=StatusLider.choices,
        default=StatusLider.ATIVO,
    )

    class Meta:
        db_table = "lideres"
        verbose_name = "líder"
        verbose_name_plural = "líderes"

    def __str__(self):
        return f"{self.get_tipo_lideranca_display()}: {self.pessoa.nome}"


class TipoContrato(models.TextChoices):
    CLT = "CLT", "CLT"
    PJ = "PJ", "PJ"
    VOLUNTARIO = "Voluntario", "Voluntário"
    ESTAGIARIO = "Estagiario", "Estagiário"


class StatusFuncionario(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    INATIVO = "inativo", "Inativo"
    LICENCIADO = "licenciado", "Licenciado"
    DEMITIDO = "demitido", "Demitido"


class Funcionario(models.Model):
    pessoa = models.OneToOneField(
        Pessoa,
        on_delete=models.CASCADE,
        related_name="funcionario",
        db_column="pessoa_id",
    )
    cargo = models.CharField(max_length=150)
    data_admissao = models.DateField(blank=True, null=True)
    data_demissao = models.DateField(blank=True, null=True)
    salario = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    tipo_contrato = models.CharField(
        max_length=20,
        choices=TipoContrato.choices,
        default=TipoContrato.VOLUNTARIO,
    )
    status = models.CharField(
        max_length=20,
        choices=StatusFuncionario.choices,
        default=StatusFuncionario.ATIVO,
    )

    class Meta:
        db_table = "funcionarios"

    def __str__(self):
        return f"Funcionário: {self.pessoa.nome}"
