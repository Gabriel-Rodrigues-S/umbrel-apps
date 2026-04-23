from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    Casal,
    Certificado,
    CategoriaFinanceira,
    ClasseAluno,
    ClasseEstudo,
    Curso,
    CursoAula,
    CursoMatricula,
    CursoModulo,
    CursoNota,
    CursoPresenca,
    Discipulado,
    Evento,
    EventoInscricao,
    EventoResponsavel,
    Familia,
    FamiliaMembro,
    Funcionario,
    Galeria,
    GaleriaFoto,
    Igreja,
    LancamentoFinanceiro,
    Lider,
    Membro,
    Mensagem,
    Ministerio,
    MinisterioMembro,
    Noticia,
    PedidoOracao,
    PequenoGrupo,
    PequenoGrupoMembro,
    Pessoa,
    User,
    Visitante,
)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = ("email", "nome", "nivel_acesso", "status", "is_staff", "is_active")
    search_fields = ("email", "nome")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Perfil",
            {"fields": ("nome", "nivel_acesso", "status", "ultimo_acesso")},
        ),
        (
            "Permissões",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Datas importantes", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "nome", "password1", "password2", "is_staff"),
            },
        ),
    )
    filter_horizontal = ("groups", "user_permissions")


admin.site.register(Igreja)
admin.site.register(Pessoa)
@admin.register(Membro)
class MembroAdmin(admin.ModelAdmin):
    list_display = ("pessoa", "status", "codigo_acesso")
    search_fields = ("pessoa__nome", "codigo_acesso")
    readonly_fields = ("codigo_acesso",)
    list_filter = ("status",)
admin.site.register(Visitante)
admin.site.register(Familia)
admin.site.register(FamiliaMembro)
admin.site.register(Casal)
admin.site.register(Lider)
admin.site.register(Funcionario)
admin.site.register(Ministerio)
admin.site.register(MinisterioMembro)
admin.site.register(PequenoGrupo)
admin.site.register(PequenoGrupoMembro)
admin.site.register(Discipulado)
admin.site.register(ClasseEstudo)
admin.site.register(ClasseAluno)
admin.site.register(CategoriaFinanceira)
admin.site.register(LancamentoFinanceiro)
admin.site.register(Curso)
admin.site.register(CursoModulo)
admin.site.register(CursoAula)
admin.site.register(CursoMatricula)
admin.site.register(CursoPresenca)
admin.site.register(CursoNota)
admin.site.register(Certificado)
admin.site.register(Evento)
admin.site.register(EventoResponsavel)
admin.site.register(EventoInscricao)
admin.site.register(Noticia)
admin.site.register(PedidoOracao)
admin.site.register(Galeria)
admin.site.register(GaleriaFoto)
admin.site.register(Mensagem)
