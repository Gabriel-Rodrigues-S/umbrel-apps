from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from church.forms import EventoForm, EventoInscricaoForm, EventoResponsavelForm
from church.models import Evento, EventoInscricao, EventoResponsavel


class EventoGestaoMixin(UserPassesTestMixin):
    """Restringe criação/edição/exclusão de eventos a admins, pastores e líderes."""
    raise_exception = True

    def test_func(self):
        return self.request.user.has_role("admin", "pastor", "lider")


class EventoListView(LoginRequiredMixin, ListView):
    model = Evento
    template_name = "app/eventos/listar.html"
    context_object_name = "eventos"


class EventoDetailView(LoginRequiredMixin, DetailView):
    model = Evento
    template_name = "app/detail_padrao.html"
    context_object_name = "evento"


class EventoCreateView(LoginRequiredMixin, EventoGestaoMixin, CreateView):
    model = Evento
    form_class = EventoForm
    template_name = "app/eventos/cadastrar.html"
    success_url = reverse_lazy("eventos_listar")

    def form_valid(self, form):
        form.instance.criado_por = self.request.user
        messages.success(self.request, "Evento cadastrado!")
        return super().form_valid(form)


class EventoUpdateView(LoginRequiredMixin, EventoGestaoMixin, UpdateView):
    model = Evento
    form_class = EventoForm
    template_name = "app/eventos/editar.html"
    success_url = reverse_lazy("eventos_listar")

    def form_valid(self, form):
        messages.success(self.request, "Evento atualizado!")
        return super().form_valid(form)


class EventoDeleteView(LoginRequiredMixin, EventoGestaoMixin, DeleteView):
    model = Evento
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("eventos_listar")

    def form_valid(self, form):
        messages.success(self.request, "Evento excluído.")
        return super().form_valid(form)


class EventoResponsavelListView(LoginRequiredMixin, ListView):
    model = EventoResponsavel
    template_name = "app/eventos/responsaveis.html"
    context_object_name = "responsaveis"

    def get_queryset(self):
        return EventoResponsavel.objects.select_related("evento", "pessoa").order_by(
            "evento__data_inicio"
        )


class EventoResponsavelCreateView(LoginRequiredMixin, EventoGestaoMixin, CreateView):
    model = EventoResponsavel
    form_class = EventoResponsavelForm
    template_name = "app/eventos/cadastrar_responsavel.html"
    success_url = reverse_lazy("eventos_responsaveis")

    def form_valid(self, form):
        messages.success(self.request, "Responsável adicionado!")
        return super().form_valid(form)


class EventoInscricaoListView(LoginRequiredMixin, ListView):
    model = EventoInscricao
    template_name = "app/eventos/inscricoes.html"
    context_object_name = "inscricoes"

    def get_queryset(self):
        return EventoInscricao.objects.select_related("evento", "pessoa").order_by(
            "-data_inscricao"
        )


class EventoInscricaoCreateView(LoginRequiredMixin, EventoGestaoMixin, CreateView):
    model = EventoInscricao
    form_class = EventoInscricaoForm
    template_name = "app/eventos/nova_inscricao.html"
    success_url = reverse_lazy("eventos_inscricoes")

    def form_valid(self, form):
        messages.success(self.request, "Inscrição registrada!")
        return super().form_valid(form)


class EventoInscricaoUpdateView(LoginRequiredMixin, EventoGestaoMixin, UpdateView):
    model = EventoInscricao
    form_class = EventoInscricaoForm
    template_name = "app/eventos/editar_inscricao.html"
    success_url = reverse_lazy("eventos_inscricoes")

    def form_valid(self, form):
        messages.success(self.request, "Inscrição atualizada!")
        return super().form_valid(form)
