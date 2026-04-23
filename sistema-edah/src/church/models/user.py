from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models


class NivelAcesso(models.TextChoices):
    ADMIN = "admin", "Admin"
    PASTOR = "pastor", "Pastor"
    LIDER = "lider", "Líder"
    SECRETARIA = "secretaria", "Secretaria"
    FINANCEIRO = "financeiro", "Financeiro"
    USUARIO = "usuario", "Usuário"


class StatusUsuario(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    INATIVO = "inativo", "Inativo"


class TemaPreferencia(models.TextChoices):
    CLARO = "light", "Claro"
    ESCURO = "dark", "Escuro"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("O e-mail é obrigatório")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("nivel_acesso", NivelAcesso.ADMIN)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser precisa is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser precisa is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField("e-mail", unique=True)
    nome = models.CharField(max_length=200)
    nivel_acesso = models.CharField(
        max_length=20,
        choices=NivelAcesso.choices,
        default=NivelAcesso.USUARIO,
    )
    status = models.CharField(
        max_length=10,
        choices=StatusUsuario.choices,
        default=StatusUsuario.ATIVO,
    )
    theme_preference = models.CharField(
        max_length=10,
        choices=TemaPreferencia.choices,
        default=TemaPreferencia.CLARO,
        verbose_name="preferência de tema",
        help_text="Tema preferido do usuário: claro ou escuro",
    )
    ultimo_acesso = models.DateTimeField(null=True, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nome"]

    objects = UserManager()

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        db_table = "usuarios"

    def has_role(self, *roles: str) -> bool:
        """Retorna True se o usuário tem superuser ou um dos roles informados."""
        if self.is_superuser:
            return True
        return self.nivel_acesso in roles

    def __str__(self):
        return self.nome
