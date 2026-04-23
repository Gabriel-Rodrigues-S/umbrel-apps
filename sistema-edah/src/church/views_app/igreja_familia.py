from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import DetailView, ListView

from church.forms import CasalForm, FamiliaForm, FamiliaMembroForm, IgrejaForm
from church.models import Casal, Familia, FamiliaMembro, Igreja


class IgrejaEditView(LoginRequiredMixin, View):
    template_name = "app/igreja/editar.html"

    def get_object(self):
        obj = Igreja.objects.order_by("pk").first()
        if obj is None:
            obj = Igreja.objects.create(nome="Igreja EDAH")
        return obj

    def get(self, request):
        return render(
            request,
            self.template_name,
            {"form": IgrejaForm(instance=self.get_object())},
        )

    def post(self, request):
        form = IgrejaForm(request.POST, instance=self.get_object())
        if form.is_valid():
            form.save()
            messages.success(request, "Dados da igreja salvos com sucesso!")
            return redirect("igreja_editar")
        return render(request, self.template_name, {"form": form})


class FamiliaListView(LoginRequiredMixin, ListView):
    model = Familia
    template_name = "app/familias/listar.html"
    context_object_name = "familias"


class FamiliaDetailView(LoginRequiredMixin, DetailView):
    model = Familia
    template_name = "app/detail_padrao.html"
    context_object_name = "familia"


class FamiliaCreateView(LoginRequiredMixin, View):
    template_name = "app/familias/cadastrar.html"

    def get(self, request):
        return render(request, self.template_name, {"form": FamiliaForm()})

    def post(self, request):
        form = FamiliaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Família cadastrada com sucesso!")
            return redirect("familias_listar")
        return render(request, self.template_name, {"form": form})


class FamiliaUpdateView(LoginRequiredMixin, View):
    template_name = "app/familias/editar.html"

    def get(self, request, pk):
        f = Familia.objects.get(pk=pk)
        return render(request, self.template_name, {"familia": f, "form": FamiliaForm(instance=f)})

    def post(self, request, pk):
        f = Familia.objects.get(pk=pk)
        form = FamiliaForm(request.POST, instance=f)
        if form.is_valid():
            form.save()
            messages.success(request, "Família atualizada com sucesso!")
            return redirect("familias_listar")
        return render(request, self.template_name, {"familia": f, "form": form})


class FamiliaMembroListView(LoginRequiredMixin, ListView):
    model = FamiliaMembro
    template_name = "app/familias/membros.html"
    context_object_name = "vinculos"

    def get_queryset(self):
        return FamiliaMembro.objects.select_related("familia", "pessoa").order_by(
            "familia__nome_familia", "pessoa__nome"
        )


class FamiliaMembroCreateView(LoginRequiredMixin, View):
    template_name = "app/familias/vincular_membro.html"

    def get(self, request):
        return render(request, self.template_name, {"form": FamiliaMembroForm()})

    def post(self, request):
        form = FamiliaMembroForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Membro vinculado à família!")
            return redirect("familias_membros")
        return render(request, self.template_name, {"form": form})


class CasalListView(LoginRequiredMixin, ListView):
    model = Casal
    template_name = "app/familias/casais.html"
    context_object_name = "casais"

    def get_queryset(self):
        return Casal.objects.select_related("esposo", "esposa", "familia").order_by("-pk")


class CasalCreateView(LoginRequiredMixin, View):
    template_name = "app/familias/cadastrar_casal.html"

    def get(self, request):
        return render(request, self.template_name, {"form": CasalForm()})

    def post(self, request):
        form = CasalForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Casal cadastrado!")
            return redirect("familias_casais")
        return render(request, self.template_name, {"form": form})
