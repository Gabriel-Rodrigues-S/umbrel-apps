from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from church.forms import MinisterioForm, MinisterioMembroForm, PequenoGrupoForm, PequenoGrupoMembroForm
from church.models import Ministerio, MinisterioMembro, PequenoGrupo, PequenoGrupoMembro


class GruposGestaoMixin(UserPassesTestMixin):
    """Restringe criação/edição/exclusão de grupos e ministérios a admins, pastores e líderes."""
    raise_exception = True

    def test_func(self):
        return self.request.user.has_role("admin", "pastor", "lider")


class PequenoGrupoListView(LoginRequiredMixin, ListView):
    model = PequenoGrupo
    template_name = "app/pequenos_grupos/listar.html"
    context_object_name = "grupos"


class PequenoGrupoDetailView(LoginRequiredMixin, DetailView):
    model = PequenoGrupo
    template_name = "app/detail_padrao.html"
    context_object_name = "grupo"


class PequenoGrupoCreateView(LoginRequiredMixin, GruposGestaoMixin, CreateView):
    model = PequenoGrupo
    form_class = PequenoGrupoForm
    template_name = "app/pequenos_grupos/cadastrar.html"
    success_url = reverse_lazy("pequenos_grupos_listar")

    def form_valid(self, form):
        messages.success(self.request, "Grupo cadastrado!")
        return super().form_valid(form)


class PequenoGrupoUpdateView(LoginRequiredMixin, GruposGestaoMixin, UpdateView):
    model = PequenoGrupo
    form_class = PequenoGrupoForm
    template_name = "app/pequenos_grupos/editar.html"
    success_url = reverse_lazy("pequenos_grupos_listar")

    def form_valid(self, form):
        messages.success(self.request, "Grupo atualizado!")
        return super().form_valid(form)


class PequenoGrupoDeleteView(LoginRequiredMixin, GruposGestaoMixin, DeleteView):
    model = PequenoGrupo
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("pequenos_grupos_listar")

    def form_valid(self, form):
        messages.success(self.request, "Grupo excluído.")
        return super().form_valid(form)


class PequenoGrupoMembroListView(LoginRequiredMixin, ListView):
    model = PequenoGrupoMembro
    template_name = "app/pequenos_grupos/membros.html"
    context_object_name = "vinculos"

    def get_queryset(self):
        return PequenoGrupoMembro.objects.select_related("grupo", "pessoa").order_by(
            "grupo__nome", "pessoa__nome"
        )


class PequenoGrupoMembroCreateView(LoginRequiredMixin, GruposGestaoMixin, CreateView):
    model = PequenoGrupoMembro
    form_class = PequenoGrupoMembroForm
    template_name = "app/pequenos_grupos/vincular_membro.html"
    success_url = reverse_lazy("pequenos_grupos_membros")

    def form_valid(self, form):
        messages.success(self.request, "Membro vinculado ao grupo!")
        return super().form_valid(form)


class MinisterioListView(LoginRequiredMixin, ListView):
    model = Ministerio
    template_name = "app/ministerios/listar.html"
    context_object_name = "ministerios"


class MinisterioDetailView(LoginRequiredMixin, DetailView):
    model = Ministerio
    template_name = "app/detail_padrao.html"
    context_object_name = "ministerio"


class MinisterioCreateView(LoginRequiredMixin, GruposGestaoMixin, CreateView):
    model = Ministerio
    form_class = MinisterioForm
    template_name = "app/ministerios/cadastrar.html"
    success_url = reverse_lazy("ministerios_listar")

    def form_valid(self, form):
        messages.success(self.request, "Ministério cadastrado!")
        return super().form_valid(form)


class MinisterioUpdateView(LoginRequiredMixin, GruposGestaoMixin, UpdateView):
    model = Ministerio
    form_class = MinisterioForm
    template_name = "app/ministerios/editar.html"
    success_url = reverse_lazy("ministerios_listar")

    def form_valid(self, form):
        messages.success(self.request, "Ministério atualizado!")
        return super().form_valid(form)


class MinisterioDeleteView(LoginRequiredMixin, GruposGestaoMixin, DeleteView):
    model = Ministerio
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("ministerios_listar")

    def form_valid(self, form):
        messages.success(self.request, "Ministério excluído.")
        return super().form_valid(form)


class MinisterioMembroListView(LoginRequiredMixin, ListView):
    model = MinisterioMembro
    template_name = "app/ministerios/membros.html"
    context_object_name = "vinculos"

    def get_queryset(self):
        return MinisterioMembro.objects.select_related("ministerio", "pessoa").order_by(
            "ministerio__nome", "pessoa__nome"
        )


class MinisterioMembroCreateView(LoginRequiredMixin, GruposGestaoMixin, CreateView):
    model = MinisterioMembro
    form_class = MinisterioMembroForm
    template_name = "app/ministerios/vincular_membro.html"
    success_url = reverse_lazy("ministerios_membros")

    def form_valid(self, form):
        messages.success(self.request, "Membro vinculado ao ministério!")
        return super().form_valid(form)
