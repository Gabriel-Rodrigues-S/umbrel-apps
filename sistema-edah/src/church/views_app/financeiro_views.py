from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Sum
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from church.forms import CategoriaFinanceiraForm, LancamentoFinanceiroForm
from church.models import CategoriaFinanceira, LancamentoFinanceiro, TipoLancamento


class FinanceiroRoleRequiredMixin(UserPassesTestMixin):
    raise_exception = True

    def test_func(self):
        return self.request.user.has_role("admin", "pastor", "financeiro")


class LancamentoListView(LoginRequiredMixin, FinanceiroRoleRequiredMixin, ListView):
    model = LancamentoFinanceiro
    template_name = "app/financeiro/lancamentos.html"
    context_object_name = "lancamentos"
    paginate_by = 50

    def get_queryset(self):
        return LancamentoFinanceiro.objects.select_related(
            "categoria", "pessoa", "usuario"
        ).order_by("-data_lancamento", "-pk")


class LancamentoCreateView(LoginRequiredMixin, FinanceiroRoleRequiredMixin, CreateView):
    model = LancamentoFinanceiro
    form_class = LancamentoFinanceiroForm
    template_name = "app/financeiro/novo_lancamento.html"
    success_url = reverse_lazy("financeiro_lancamentos")

    def form_valid(self, form):
        form.instance.usuario = self.request.user
        messages.success(self.request, "Lançamento registrado!")
        return super().form_valid(form)


class LancamentoUpdateView(LoginRequiredMixin, FinanceiroRoleRequiredMixin, UpdateView):
    model = LancamentoFinanceiro
    form_class = LancamentoFinanceiroForm
    template_name = "app/financeiro/editar_lancamento.html"
    success_url = reverse_lazy("financeiro_lancamentos")

    def form_valid(self, form):
        messages.success(self.request, "Lançamento atualizado!")
        return super().form_valid(form)


class LancamentoDeleteView(LoginRequiredMixin, FinanceiroRoleRequiredMixin, DeleteView):
    model = LancamentoFinanceiro
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("financeiro_lancamentos")

    def form_valid(self, form):
        messages.success(self.request, "Lançamento excluído.")
        return super().form_valid(form)


class DizimoListView(LoginRequiredMixin, FinanceiroRoleRequiredMixin, ListView):
    model = LancamentoFinanceiro
    template_name = "app/financeiro/dizimos.html"
    context_object_name = "lancamentos"
    paginate_by = 50

    def get_queryset(self):
        return (
            LancamentoFinanceiro.objects.filter(tipo=TipoLancamento.DIZIMO)
            .select_related("categoria", "pessoa")
            .order_by("-data_lancamento")
        )


class OfertaListView(LoginRequiredMixin, FinanceiroRoleRequiredMixin, ListView):
    model = LancamentoFinanceiro
    template_name = "app/financeiro/ofertas.html"
    context_object_name = "lancamentos"
    paginate_by = 50

    def get_queryset(self):
        return (
            LancamentoFinanceiro.objects.filter(tipo=TipoLancamento.OFERTA)
            .select_related("categoria", "pessoa")
            .order_by("-data_lancamento")
        )


class FinanceiroRelatoriosView(LoginRequiredMixin, FinanceiroRoleRequiredMixin, TemplateView):
    template_name = "app/financeiro/relatorios.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = LancamentoFinanceiro.objects.all()
        entradas = qs.filter(
            tipo__in=[
                TipoLancamento.DIZIMO,
                TipoLancamento.OFERTA,
                TipoLancamento.DOACAO,
            ]
        ).aggregate(t=Sum("valor"))["t"] or 0
        saidas = qs.filter(tipo=TipoLancamento.SAIDA).aggregate(t=Sum("valor"))["t"] or 0
        ctx["total_entradas"] = entradas
        ctx["total_saidas"] = saidas
        ctx["saldo"] = entradas - saidas
        return ctx


class CategoriaFinanceiraListView(LoginRequiredMixin, FinanceiroRoleRequiredMixin, ListView):
    model = CategoriaFinanceira
    template_name = "app/financeiro/categorias.html"
    context_object_name = "categorias"
