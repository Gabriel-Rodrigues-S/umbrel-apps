from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count
from django.views.generic import TemplateView

from church.models import Evento, Membro, PequenoGrupo, Visitante

ROLES_RELATORIOS = {"admin", "pastor", "secretaria", "financeiro"}


class RelatoriosRoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    raise_exception = True

    def test_func(self):
        return self.request.user.has_role(*ROLES_RELATORIOS)


class RelatoriosIndexView(RelatoriosRoleRequiredMixin, TemplateView):
    template_name = "app/relatorios/index.html"


class RelatorioMembrosView(RelatoriosRoleRequiredMixin, TemplateView):
    template_name = "app/relatorios/membros.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total"] = Membro.objects.count()
        ctx["por_status"] = (
            Membro.objects.values("status").annotate(c=Count("id")).order_by("-c")
        )
        return ctx


class RelatorioVisitantesView(RelatoriosRoleRequiredMixin, TemplateView):
    template_name = "app/relatorios/visitantes.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total"] = Visitante.objects.count()
        return ctx


class RelatorioGruposView(RelatoriosRoleRequiredMixin, TemplateView):
    template_name = "app/relatorios/grupos.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total"] = PequenoGrupo.objects.count()
        return ctx


class RelatorioEventosView(RelatoriosRoleRequiredMixin, TemplateView):
    template_name = "app/relatorios/eventos.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total"] = Evento.objects.count()
        return ctx


class RelatorioCursosView(RelatoriosRoleRequiredMixin, TemplateView):
    template_name = "app/relatorios/cursos.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from church.models import Curso

        ctx["total"] = Curso.objects.count()
        return ctx
