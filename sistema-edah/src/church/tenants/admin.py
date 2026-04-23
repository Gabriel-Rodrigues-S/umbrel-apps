from django.contrib import admin
from django_tenants.admin import TenantAdminMixin

from .models import Domain, Igreja


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 1


@admin.register(Igreja)
class IgrejaAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display   = ("nome", "schema_name", "ativo", "assinatura_ativa", "data_criacao", "data_expiracao")
    list_filter    = ("ativo",)
    readonly_fields = ("data_criacao", "assinatura_ativa")
    search_fields  = ("nome", "email_contato", "responsavel", "codigo_acesso")
    inlines        = [DomainInline]

    def get_readonly_fields(self, request, obj=None):
        # schema_name só pode ser definido na criação; após salvo, não pode mudar
        if obj:
            return ("data_criacao", "schema_name", "assinatura_ativa")
        return ("data_criacao", "assinatura_ativa")

    fieldsets = (
        ("Identificação", {
            "fields": ("nome", "schema_name", "codigo_acesso"),
        }),
        ("Contato", {
            "fields": ("email_contato", "telefone_contato", "responsavel"),
        }),
        ("Assinatura", {
            "fields": ("ativo", "data_expiracao", "assinatura_ativa", "observacoes"),
        }),
        ("Auditoria", {
            "fields": ("data_criacao",),
            "classes": ("collapse",),
        }),
    )
