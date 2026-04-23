from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from church.forms import ClasseAlunoForm, ClasseEstudoForm, DiscipuladoForm
from church.models import ClasseAluno, ClasseEstudo, Discipulado


class DiscipuladoGestaoMixin(UserPassesTestMixin):
    """Restringe criação/edição/exclusão de discipulado e classes a admins, pastores e líderes."""
    raise_exception = True

    def test_func(self):
        return self.request.user.has_role("admin", "pastor", "lider")


class DiscipuladoListView(LoginRequiredMixin, ListView):
    model = Discipulado
    template_name = "app/discipulado/listar.html"
    context_object_name = "itens"


class DiscipuladoDetailView(LoginRequiredMixin, DetailView):
    model = Discipulado
    template_name = "app/detail_padrao.html"
    context_object_name = "item"


class DiscipuladoCreateView(LoginRequiredMixin, DiscipuladoGestaoMixin, CreateView):
    model = Discipulado
    form_class = DiscipuladoForm
    template_name = "app/discipulado/cadastrar.html"
    success_url = reverse_lazy("discipulado_listar")

    def form_valid(self, form):
        messages.success(self.request, "Discipulado registrado com sucesso!")
        return super().form_valid(form)


class DiscipuladoUpdateView(LoginRequiredMixin, DiscipuladoGestaoMixin, UpdateView):
    model = Discipulado
    form_class = DiscipuladoForm
    template_name = "app/discipulado/editar.html"
    success_url = reverse_lazy("discipulado_listar")

    def form_valid(self, form):
        messages.success(self.request, "Registro atualizado!")
        return super().form_valid(form)


class DiscipuladoDeleteView(LoginRequiredMixin, DiscipuladoGestaoMixin, DeleteView):
    model = Discipulado
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("discipulado_listar")

    def form_valid(self, form):
        messages.success(self.request, "Excluído com sucesso.")
        return super().form_valid(form)


class ClasseEstudoListView(LoginRequiredMixin, ListView):
    model = ClasseEstudo
    template_name = "app/classes/listar.html"
    context_object_name = "classes"


class ClasseEstudoDetailView(LoginRequiredMixin, DetailView):
    model = ClasseEstudo
    template_name = "app/detail_padrao.html"
    context_object_name = "classe"


class ClasseEstudoCreateView(LoginRequiredMixin, DiscipuladoGestaoMixin, CreateView):
    model = ClasseEstudo
    form_class = ClasseEstudoForm
    template_name = "app/classes/cadastrar.html"
    success_url = reverse_lazy("classes_listar")

    def form_valid(self, form):
        messages.success(self.request, "Classe cadastrada!")
        return super().form_valid(form)


class ClasseEstudoUpdateView(LoginRequiredMixin, DiscipuladoGestaoMixin, UpdateView):
    model = ClasseEstudo
    form_class = ClasseEstudoForm
    template_name = "app/classes/editar.html"
    success_url = reverse_lazy("classes_listar")

    def form_valid(self, form):
        messages.success(self.request, "Classe atualizada!")
        return super().form_valid(form)


class ClasseEstudoDeleteView(LoginRequiredMixin, DiscipuladoGestaoMixin, DeleteView):
    model = ClasseEstudo
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("classes_listar")

    def form_valid(self, form):
        messages.success(self.request, "Classe excluída.")
        return super().form_valid(form)


class ClasseAlunoListView(LoginRequiredMixin, ListView):
    model = ClasseAluno
    template_name = "app/classes/alunos.html"
    context_object_name = "alunos"

    def get_queryset(self):
        return ClasseAluno.objects.select_related("classe", "pessoa").order_by(
            "classe__nome", "pessoa__nome"
        )


class ClasseAlunoCreateView(LoginRequiredMixin, DiscipuladoGestaoMixin, CreateView):
    model = ClasseAluno
    form_class = ClasseAlunoForm
    template_name = "app/classes/cadastrar_aluno.html"
    success_url = reverse_lazy("classes_alunos")

    def form_valid(self, form):
        messages.success(self.request, "Aluno vinculado à classe!")
        return super().form_valid(form)
