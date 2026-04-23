from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from church.forms import (
    CertificadoForm,
    CursoAulaForm,
    CursoForm,
    CursoMatriculaForm,
    CursoModuloForm,
    CursoNotaForm,
    CursoPresencaForm,
)
from church.models import Certificado, Curso, CursoAula, CursoMatricula, CursoModulo, CursoNota, CursoPresenca


class CursoListView(LoginRequiredMixin, ListView):
    model = Curso
    template_name = "app/cursos/listar.html"
    context_object_name = "cursos"


class CursoDetailView(LoginRequiredMixin, DetailView):
    model = Curso
    template_name = "app/detail_padrao.html"
    context_object_name = "curso"


class CursoCreateView(LoginRequiredMixin, CreateView):
    model = Curso
    form_class = CursoForm
    template_name = "app/cursos/cadastrar.html"
    success_url = reverse_lazy("cursos_listar")

    def form_valid(self, form):
        messages.success(self.request, "Curso cadastrado!")
        return super().form_valid(form)


class CursoUpdateView(LoginRequiredMixin, UpdateView):
    model = Curso
    form_class = CursoForm
    template_name = "app/cursos/editar.html"
    success_url = reverse_lazy("cursos_listar")

    def form_valid(self, form):
        messages.success(self.request, "Curso atualizado!")
        return super().form_valid(form)


class CursoDeleteView(LoginRequiredMixin, DeleteView):
    model = Curso
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("cursos_listar")

    def form_valid(self, form):
        messages.success(self.request, "Curso excluído.")
        return super().form_valid(form)


class CursoModuloListView(LoginRequiredMixin, ListView):
    model = CursoModulo
    template_name = "app/cursos/modulos.html"
    context_object_name = "modulos"

    def get_queryset(self):
        return CursoModulo.objects.select_related("curso").order_by("curso__nome", "ordem")


class CursoModuloCreateView(LoginRequiredMixin, CreateView):
    model = CursoModulo
    form_class = CursoModuloForm
    template_name = "app/cursos/cadastrar_modulo.html"
    success_url = reverse_lazy("cursos_modulos")

    def form_valid(self, form):
        messages.success(self.request, "Módulo cadastrado!")
        return super().form_valid(form)


class CursoAulaListView(LoginRequiredMixin, ListView):
    model = CursoAula
    template_name = "app/cursos/aulas.html"
    context_object_name = "aulas"

    def get_queryset(self):
        return CursoAula.objects.select_related("modulo__curso").order_by(
            "modulo__curso__nome", "modulo__ordem", "ordem"
        )


class CursoAulaCreateView(LoginRequiredMixin, CreateView):
    model = CursoAula
    form_class = CursoAulaForm
    template_name = "app/cursos/cadastrar_aula.html"
    success_url = reverse_lazy("cursos_aulas")

    def form_valid(self, form):
        messages.success(self.request, "Aula cadastrada!")
        return super().form_valid(form)


class CursoMatriculaListView(LoginRequiredMixin, ListView):
    model = CursoMatricula
    template_name = "app/cursos/matriculas.html"
    context_object_name = "matriculas"

    def get_queryset(self):
        return CursoMatricula.objects.select_related("curso", "pessoa").order_by(
            "curso__nome", "pessoa__nome"
        )


class CursoMatriculaCreateView(LoginRequiredMixin, CreateView):
    model = CursoMatricula
    form_class = CursoMatriculaForm
    template_name = "app/cursos/nova_matricula.html"
    success_url = reverse_lazy("cursos_matriculas")

    def form_valid(self, form):
        messages.success(self.request, "Matrícula registrada!")
        return super().form_valid(form)


class CursoMatriculaDetailView(LoginRequiredMixin, DetailView):
    model = CursoMatricula
    template_name = "app/detail_padrao.html"
    context_object_name = "matricula"


class CursoMatriculaUpdateView(LoginRequiredMixin, UpdateView):
    model = CursoMatricula
    form_class = CursoMatriculaForm
    template_name = "app/cursos/editar_matricula.html"
    success_url = reverse_lazy("cursos_matriculas")

    def form_valid(self, form):
        messages.success(self.request, "Matrícula atualizada!")
        return super().form_valid(form)


class CursoPresencaListView(LoginRequiredMixin, ListView):
    model = CursoPresenca
    template_name = "app/cursos/presencas.html"
    context_object_name = "presencas"

    def get_queryset(self):
        return CursoPresenca.objects.select_related("aula__modulo__curso", "matricula__pessoa").order_by(
            "-data_aula"
        )


class CursoPresencaCreateView(LoginRequiredMixin, CreateView):
    model = CursoPresenca
    form_class = CursoPresencaForm
    template_name = "app/cursos/registrar_presenca.html"
    success_url = reverse_lazy("cursos_presencas")

    def form_valid(self, form):
        messages.success(self.request, "Presença registrada!")
        return super().form_valid(form)


class CursoNotaListView(LoginRequiredMixin, ListView):
    model = CursoNota
    template_name = "app/cursos/notas.html"
    context_object_name = "notas"

    def get_queryset(self):
        return CursoNota.objects.select_related("modulo__curso", "matricula__pessoa").order_by("-pk")


class CursoNotaCreateView(LoginRequiredMixin, CreateView):
    model = CursoNota
    form_class = CursoNotaForm
    template_name = "app/cursos/registrar_nota.html"
    success_url = reverse_lazy("cursos_notas")

    def form_valid(self, form):
        messages.success(self.request, "Nota registrada!")
        return super().form_valid(form)


class CertificadoListView(LoginRequiredMixin, ListView):
    model = Certificado
    template_name = "app/cursos/certificados.html"
    context_object_name = "certificados"

    def get_queryset(self):
        return Certificado.objects.select_related("matricula__curso", "matricula__pessoa").order_by(
            "-data_emissao"
        )


class CertificadoDetailView(LoginRequiredMixin, DetailView):
    model = Certificado
    template_name = "app/cursos/visualizar_certificado.html"
    context_object_name = "certificado"


class CertificadoCreateView(LoginRequiredMixin, CreateView):
    model = Certificado
    form_class = CertificadoForm
    template_name = "app/cursos/gerar_certificado.html"
    success_url = reverse_lazy("cursos_certificados")

    def form_valid(self, form):
        messages.success(self.request, "Certificado registrado!")
        return super().form_valid(form)


class CertificadoUpdateView(LoginRequiredMixin, UpdateView):
    model = Certificado
    form_class = CertificadoForm
    template_name = "app/cursos/editar_certificado.html"
    success_url = reverse_lazy("cursos_certificados")

    def form_valid(self, form):
        messages.success(self.request, "Certificado atualizado!")
        return super().form_valid(form)


class CertificadoEnviarPlaceholderView(LoginRequiredMixin, TemplateView):
    template_name = "app/cursos/enviar_certificado.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["mensagem"] = (
            "Envio por e-mail requer SMTP configurado. Use os dados do certificado abaixo."
        )
        return ctx
