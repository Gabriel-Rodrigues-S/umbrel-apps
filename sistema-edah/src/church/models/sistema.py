from django.conf import settings
from django.db import models


class DispositivoFCM(models.Model):
    class Plataforma(models.TextChoices):
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dispositivos_fcm",
    )
    token = models.TextField(unique=True)
    plataforma = models.CharField(max_length=10, choices=Plataforma.choices)
    ativo = models.BooleanField(default=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "dispositivos_fcm"


class ConfiguracaoIgreja(models.Model):
    """
    Configurações específicas desta igreja dentro do seu schema de tenant.
    Substitui o antigo model Igreja de cadastros.py no contexto multi-tenant:
    cada schema de tenant tem sua própria ConfiguracaoIgreja.
    """
    nome_exibicao     = models.CharField(max_length=200)
    cnpj              = models.CharField(max_length=18, blank=True)
    endereco          = models.TextField(blank=True)
    cidade            = models.CharField(max_length=100, blank=True)
    estado            = models.CharField(max_length=2, blank=True)
    cep               = models.CharField(max_length=10, blank=True)
    telefone          = models.CharField(max_length=20, blank=True)
    email             = models.CharField(max_length=150, blank=True)
    site              = models.CharField(max_length=200, blank=True)
    pastor_presidente = models.CharField(max_length=200, blank=True)
    data_fundacao     = models.DateField(blank=True, null=True)
    logo              = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "configuracao_igreja"
        verbose_name = "Configuração da Igreja"

    def __str__(self):
        return self.nome_exibicao
