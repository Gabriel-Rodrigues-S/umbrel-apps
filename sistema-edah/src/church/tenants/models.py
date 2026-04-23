from datetime import date

from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Igreja(TenantMixin):
    """
    Model principal do tenant. Cada instância = um schema PostgreSQL.
    Fica no schema 'public', visível apenas via painel super-admin.
    """
    nome             = models.CharField(max_length=200)
    codigo_acesso    = models.CharField(
        max_length=20,
        unique=True,
        help_text="Código curto para identificação no app (ex: IBMANAUS)",
    )
    email_contato    = models.EmailField()
    telefone_contato = models.CharField(max_length=20, blank=True)
    responsavel      = models.CharField(max_length=200, help_text="Nome do pastor/responsável")
    ativo            = models.BooleanField(
        default=True,
        verbose_name="Assinatura ativa",
        help_text="Desmarque para suspender o acesso da igreja ao sistema.",
    )
    data_criacao     = models.DateTimeField(auto_now_add=True)
    data_expiracao   = models.DateField(
        null=True,
        blank=True,
        verbose_name="Vencimento da assinatura",
        help_text="Vazio = sem expiração. Após esta data a assinatura é considerada inativa.",
    )
    observacoes      = models.TextField(blank=True)

    # django-tenants cria o schema automaticamente ao salvar
    auto_create_schema = True

    class Meta:
        app_label = "tenants"
        verbose_name = "Igreja"
        verbose_name_plural = "Igrejas"

    def __str__(self):
        return self.nome

    @property
    def assinatura_ativa(self) -> bool:
        """True quando ativo=True e dentro do prazo de vencimento."""
        if not self.ativo:
            return False
        if self.data_expiracao and self.data_expiracao < date.today():
            return False
        return True


class Domain(DomainMixin):
    """
    Cada Igreja pode ter um ou mais domínios/subdomínios.
    Ex: batista-manaus.seuapp.com.br (primário) + domínio customizado.
    """
    class Meta:
        app_label = "tenants"
        verbose_name = "Domínio"
        verbose_name_plural = "Domínios"
