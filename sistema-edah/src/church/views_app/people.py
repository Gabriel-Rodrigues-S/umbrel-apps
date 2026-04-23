from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, ListView

from church.forms import FuncionarioForm, LiderForm, MembroForm, PessoaForm, VisitanteForm
from church.models import Funcionario, Lider, Membro, Pessoa, StatusMembro, TipoPessoa, Visitante


class CadastroPessoasRoleRequiredMixin(UserPassesTestMixin):
    raise_exception = True

    def test_func(self):
        return self.request.user.has_role("admin", "pastor", "secretaria", "lider")


class MembroListView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, ListView):
    model = Membro
    template_name = "app/membros/listar.html"
    context_object_name = "membros"

    def get_queryset(self):
        return Membro.objects.select_related("pessoa").order_by("pessoa__nome")


class MembroDetailView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, DetailView):
    model = Membro
    template_name = "app/detail_padrao.html"
    context_object_name = "membro"


class MembroCreateView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, View):
    template_name = "app/membros/cadastrar.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {"pessoa_form": PessoaForm(), "membro_form": MembroForm()},
        )

    def post(self, request):
        pf = PessoaForm(request.POST)
        mf = MembroForm(request.POST)
        if pf.is_valid() and mf.is_valid():
            with transaction.atomic():
                p = pf.save(commit=False)
                p.tipo = TipoPessoa.MEMBRO
                p.cadastrado_por = request.user
                p.save()
                m = mf.save(commit=False)
                m.pessoa = p
                m.save()
            messages.success(request, "Membro cadastrado com sucesso!")
            return redirect("membros_listar")
        return render(
            request,
            self.template_name,
            {"pessoa_form": pf, "membro_form": mf},
        )


class MembroUpdateView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, View):
    template_name = "app/membros/editar.html"

    def dispatch(self, request, *args, **kwargs):
        self.membro = get_object_or_404(Membro.objects.select_related("pessoa"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        return render(
            request,
            self.template_name,
            {
                "membro": self.membro,
                "pessoa_form": PessoaForm(instance=self.membro.pessoa),
                "membro_form": MembroForm(instance=self.membro),
            },
        )

    def post(self, request, pk):
        pf = PessoaForm(request.POST, instance=self.membro.pessoa)
        mf = MembroForm(request.POST, instance=self.membro)
        if pf.is_valid() and mf.is_valid():
            pf.save()
            mf.save()
            messages.success(request, "Membro atualizado com sucesso!")
            return redirect("membros_listar")
        return render(
            request,
            self.template_name,
            {"membro": self.membro, "pessoa_form": pf, "membro_form": mf},
        )


class VisitanteListView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, ListView):
    model = Visitante
    template_name = "app/visitantes/listar.html"
    context_object_name = "visitantes"

    def get_queryset(self):
        return Visitante.objects.select_related("pessoa").order_by("pessoa__nome")


class VisitanteDetailView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, DetailView):
    model = Visitante
    template_name = "app/detail_padrao.html"
    context_object_name = "visitante"


class VisitanteCreateView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, View):
    template_name = "app/visitantes/cadastrar.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {"pessoa_form": PessoaForm(), "visitante_form": VisitanteForm()},
        )

    def post(self, request):
        pf = PessoaForm(request.POST)
        vf = VisitanteForm(request.POST)
        if pf.is_valid() and vf.is_valid():
            with transaction.atomic():
                p = pf.save(commit=False)
                p.tipo = TipoPessoa.VISITANTE
                p.cadastrado_por = request.user
                p.save()
                v = vf.save(commit=False)
                v.pessoa = p
                v.save()
            messages.success(request, "Visitante cadastrado com sucesso!")
            return redirect("visitantes_listar")
        return render(
            request,
            self.template_name,
            {"pessoa_form": pf, "visitante_form": vf},
        )


class VisitanteUpdateView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, View):
    template_name = "app/visitantes/editar.html"

    def dispatch(self, request, *args, **kwargs):
        self.visitante = get_object_or_404(
            Visitante.objects.select_related("pessoa"), pk=kwargs["pk"]
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        return render(
            request,
            self.template_name,
            {
                "visitante": self.visitante,
                "pessoa_form": PessoaForm(instance=self.visitante.pessoa),
                "visitante_form": VisitanteForm(instance=self.visitante),
            },
        )

    def post(self, request, pk):
        pf = PessoaForm(request.POST, instance=self.visitante.pessoa)
        vf = VisitanteForm(request.POST, instance=self.visitante)
        if pf.is_valid() and vf.is_valid():
            pf.save()
            vf.save()
            messages.success(request, "Visitante atualizado com sucesso!")
            return redirect("visitantes_listar")
        return render(
            request,
            self.template_name,
            {
                "visitante": self.visitante,
                "pessoa_form": pf,
                "visitante_form": vf,
            },
        )


class VisitanteConverterView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, View):
    template_name = "app/visitantes/converter.html"

    def get(self, request, pk):
        v = get_object_or_404(Visitante.objects.select_related("pessoa"), pk=pk)
        if v.convertido_membro:
            messages.error(request, "Este visitante já foi convertido.")
            return redirect("visitantes_listar")
        return render(
            request,
            self.template_name,
            {"visitante": v, "membro_form": MembroForm()},
        )

    def post(self, request, pk):
        v = get_object_or_404(Visitante.objects.select_related("pessoa"), pk=pk)
        if v.convertido_membro:
            return redirect("visitantes_listar")
        mf = MembroForm(request.POST)
        if mf.is_valid():
            p = v.pessoa
            vid = v.pk
            with transaction.atomic():
                Visitante.objects.filter(pk=vid).delete()
                p.tipo = TipoPessoa.MEMBRO
                p.save()
                m = mf.save(commit=False)
                m.pessoa = p
                m.save()
            messages.success(request, "Visitante convertido em membro com sucesso!")
            return redirect("membros_listar")
        return render(
            request,
            self.template_name,
            {"visitante": v, "membro_form": mf},
        )


class LiderListView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, ListView):
    model = Lider
    template_name = "app/lideres/listar.html"
    context_object_name = "lideres"

    def get_queryset(self):
        return Lider.objects.select_related("pessoa").order_by("pessoa__nome")


class LiderDetailView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, DetailView):
    model = Lider
    template_name = "app/detail_padrao.html"
    context_object_name = "lider"


class LiderCreateView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, View):
    template_name = "app/lideres/cadastrar.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {"pessoa_form": PessoaForm(), "lider_form": LiderForm()},
        )

    def post(self, request):
        pf = PessoaForm(request.POST)
        lf = LiderForm(request.POST)
        if pf.is_valid() and lf.is_valid():
            with transaction.atomic():
                p = pf.save(commit=False)
                p.tipo = TipoPessoa.CONGREGADO
                p.cadastrado_por = request.user
                p.save()
                lider = lf.save(commit=False)
                lider.pessoa = p
                lider.save()
            messages.success(request, "Líder cadastrado com sucesso!")
            return redirect("lideres_listar")
        return render(
            request,
            self.template_name,
            {"pessoa_form": pf, "lider_form": lf},
        )


class LiderUpdateView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, View):
    template_name = "app/lideres/editar.html"

    def dispatch(self, request, *args, **kwargs):
        self.lider = get_object_or_404(Lider.objects.select_related("pessoa"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        return render(
            request,
            self.template_name,
            {
                "lider": self.lider,
                "pessoa_form": PessoaForm(instance=self.lider.pessoa),
                "lider_form": LiderForm(instance=self.lider),
            },
        )

    def post(self, request, pk):
        pf = PessoaForm(request.POST, instance=self.lider.pessoa)
        lf = LiderForm(request.POST, instance=self.lider)
        if pf.is_valid() and lf.is_valid():
            pf.save()
            lf.save()
            messages.success(request, "Líder atualizado com sucesso!")
            return redirect("lideres_listar")
        return render(
            request,
            self.template_name,
            {"lider": self.lider, "pessoa_form": pf, "lider_form": lf},
        )


class FuncionarioListView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, ListView):
    model = Funcionario
    template_name = "app/funcionarios/listar.html"
    context_object_name = "funcionarios"

    def get_queryset(self):
        return Funcionario.objects.select_related("pessoa").order_by("pessoa__nome")


class FuncionarioDetailView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, DetailView):
    model = Funcionario
    template_name = "app/detail_padrao.html"
    context_object_name = "funcionario"


class FuncionarioCreateView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, View):
    template_name = "app/funcionarios/cadastrar.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {"pessoa_form": PessoaForm(), "funcionario_form": FuncionarioForm()},
        )

    def post(self, request):
        pf = PessoaForm(request.POST)
        ff = FuncionarioForm(request.POST)
        if pf.is_valid() and ff.is_valid():
            with transaction.atomic():
                p = pf.save(commit=False)
                p.tipo = TipoPessoa.MEMBRO
                p.cadastrado_por = request.user
                p.save()
                f = ff.save(commit=False)
                f.pessoa = p
                f.save()
            messages.success(request, "Funcionário cadastrado com sucesso!")
            return redirect("funcionarios_listar")
        return render(
            request,
            self.template_name,
            {"pessoa_form": pf, "funcionario_form": ff},
        )


class FuncionarioUpdateView(LoginRequiredMixin, CadastroPessoasRoleRequiredMixin, View):
    template_name = "app/funcionarios/editar.html"

    def dispatch(self, request, *args, **kwargs):
        self.funcionario = get_object_or_404(
            Funcionario.objects.select_related("pessoa"), pk=kwargs["pk"]
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        return render(
            request,
            self.template_name,
            {
                "funcionario": self.funcionario,
                "pessoa_form": PessoaForm(instance=self.funcionario.pessoa),
                "funcionario_form": FuncionarioForm(instance=self.funcionario),
            },
        )

    def post(self, request, pk):
        pf = PessoaForm(request.POST, instance=self.funcionario.pessoa)
        ff = FuncionarioForm(request.POST, instance=self.funcionario)
        if pf.is_valid() and ff.is_valid():
            pf.save()
            ff.save()
            messages.success(request, "Funcionário atualizado com sucesso!")
            return redirect("funcionarios_listar")
        return render(
            request,
            self.template_name,
            {
                "funcionario": self.funcionario,
                "pessoa_form": pf,
                "funcionario_form": ff,
            },
        )
