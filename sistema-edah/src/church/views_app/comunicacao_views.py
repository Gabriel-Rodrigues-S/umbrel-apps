from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from church.forms import GaleriaFotoForm, GaleriaForm, MensagemForm, NoticiaForm, PedidoOracaoForm
from church.models import Galeria, GaleriaFoto, Mensagem, Noticia, PedidoOracao, StatusNoticia


class NoticiaPortalView(LoginRequiredMixin, TemplateView):
    template_name = "app/noticias/portal.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["noticias"] = Noticia.objects.filter(status=StatusNoticia.PUBLICADO).order_by(
            "-data_publicacao", "-data_criacao"
        )[:50]
        return ctx


class NoticiaListView(LoginRequiredMixin, ListView):
    model = Noticia
    template_name = "app/noticias/listar.html"
    context_object_name = "noticias"
    paginate_by = 50


class NoticiaDetailView(LoginRequiredMixin, DetailView):
    model = Noticia
    template_name = "app/detail_padrao.html"
    context_object_name = "noticia"


class NoticiaCreateView(LoginRequiredMixin, CreateView):
    model = Noticia
    form_class = NoticiaForm
    template_name = "app/noticias/cadastrar.html"
    success_url = reverse_lazy("noticias_listar")

    def form_valid(self, form):
        form.instance.autor = self.request.user
        messages.success(self.request, "Notícia criada!")
        return super().form_valid(form)


class NoticiaUpdateView(LoginRequiredMixin, UpdateView):
    model = Noticia
    form_class = NoticiaForm
    template_name = "app/noticias/editar.html"
    success_url = reverse_lazy("noticias_listar")

    def form_valid(self, form):
        messages.success(self.request, "Notícia atualizada!")
        return super().form_valid(form)


class NoticiaDeleteView(LoginRequiredMixin, DeleteView):
    model = Noticia
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("noticias_listar")

    def form_valid(self, form):
        messages.success(self.request, "Notícia excluída.")
        return super().form_valid(form)


class PedidoOracaoListView(LoginRequiredMixin, ListView):
    model = PedidoOracao
    template_name = "app/pedidos_oracao/listar.html"
    context_object_name = "pedidos"


class PedidoOracaoDetailView(LoginRequiredMixin, DetailView):
    model = PedidoOracao
    template_name = "app/detail_padrao.html"
    context_object_name = "pedido"


class PedidoOracaoCreateView(LoginRequiredMixin, CreateView):
    model = PedidoOracao
    form_class = PedidoOracaoForm
    template_name = "app/pedidos_oracao/cadastrar.html"
    success_url = reverse_lazy("pedidos_oracao_listar")

    def form_valid(self, form):
        messages.success(self.request, "Pedido registrado!")
        return super().form_valid(form)


class PedidoOracaoUpdateView(LoginRequiredMixin, UpdateView):
    model = PedidoOracao
    form_class = PedidoOracaoForm
    template_name = "app/pedidos_oracao/editar.html"
    success_url = reverse_lazy("pedidos_oracao_listar")

    def form_valid(self, form):
        messages.success(self.request, "Pedido atualizado!")
        return super().form_valid(form)


class PedidoOracaoDeleteView(LoginRequiredMixin, DeleteView):
    model = PedidoOracao
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("pedidos_oracao_listar")

    def form_valid(self, form):
        messages.success(self.request, "Pedido excluído.")
        return super().form_valid(form)


class GaleriaListView(LoginRequiredMixin, ListView):
    model = Galeria
    template_name = "app/galeria/listar.html"
    context_object_name = "galerias"


class GaleriaDetailView(LoginRequiredMixin, DetailView):
    model = Galeria
    template_name = "app/detail_padrao.html"
    context_object_name = "galeria"


class GaleriaCreateView(LoginRequiredMixin, CreateView):
    model = Galeria
    form_class = GaleriaForm
    template_name = "app/galeria/cadastrar.html"
    success_url = reverse_lazy("galeria_listar")

    def form_valid(self, form):
        messages.success(self.request, "Galeria criada!")
        return super().form_valid(form)


class GaleriaUpdateView(LoginRequiredMixin, UpdateView):
    model = Galeria
    form_class = GaleriaForm
    template_name = "app/galeria/editar.html"
    success_url = reverse_lazy("galeria_listar")

    def form_valid(self, form):
        messages.success(self.request, "Galeria atualizada!")
        return super().form_valid(form)


class GaleriaDeleteView(LoginRequiredMixin, DeleteView):
    model = Galeria
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("galeria_listar")

    def form_valid(self, form):
        messages.success(self.request, "Galeria excluída.")
        return super().form_valid(form)


class GaleriaFotoListView(LoginRequiredMixin, ListView):
    model = GaleriaFoto
    template_name = "app/galeria/fotos.html"
    context_object_name = "fotos"

    def get_queryset(self):
        return GaleriaFoto.objects.select_related("galeria").order_by("galeria__titulo", "ordem")


class GaleriaFotoCreateView(LoginRequiredMixin, CreateView):
    model = GaleriaFoto
    form_class = GaleriaFotoForm
    template_name = "app/galeria/adicionar_foto.html"
    success_url = reverse_lazy("galeria_fotos")

    def form_valid(self, form):
        messages.success(self.request, "Foto adicionada!")
        return super().form_valid(form)


class MensagemListView(LoginRequiredMixin, ListView):
    model = Mensagem
    template_name = "app/mensagens/listar.html"
    context_object_name = "mensagens"
    paginate_by = 50

    def get_queryset(self):
        u = self.request.user
        return Mensagem.objects.filter(
            Q(destinatario=u) | Q(remetente=u)
        ).order_by("-data_envio")


class MensagemDetailView(LoginRequiredMixin, DetailView):
    model = Mensagem
    template_name = "app/detail_padrao.html"
    context_object_name = "mensagem"

    def get_queryset(self):
        u = self.request.user
        return Mensagem.objects.filter(Q(destinatario=u) | Q(remetente=u))


class MensagemNovaView(LoginRequiredMixin, View):
    template_name = "app/mensagens/nova.html"

    def get(self, request):
        form = MensagemForm(user=request.user)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = MensagemForm(request.POST, user=request.user)
        if form.is_valid():
            m = form.save(commit=False)
            m.remetente = request.user
            m.save()
            messages.success(request, "Mensagem enviada!")
            return redirect("mensagens_listar")
        return render(request, self.template_name, {"form": form})


class MensagemDeleteView(LoginRequiredMixin, DeleteView):
    model = Mensagem
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("mensagens_listar")

    def get_queryset(self):
        u = self.request.user
        return Mensagem.objects.filter(Q(destinatario=u) | Q(remetente=u))

    def form_valid(self, form):
        messages.success(self.request, "Mensagem excluída.")
        return super().form_valid(form)
