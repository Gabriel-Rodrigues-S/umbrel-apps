from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DeleteView, ListView, TemplateView

from church.forms import UserAdminForm, UserCreateForm, UserPasswordForm, UserProfileForm

User = get_user_model()


class PerfilView(LoginRequiredMixin, View):
    template_name = "app/perfil.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "profile_form": UserProfileForm(instance=request.user),
                "password_form": UserPasswordForm(user=request.user),
            },
        )

    def post(self, request):
        if "salvar_perfil" in request.POST:
            form = UserProfileForm(request.POST, instance=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, "Perfil atualizado!")
                return redirect("perfil")
            return render(
                request,
                self.template_name,
                {"profile_form": form, "password_form": UserPasswordForm(user=request.user)},
            )
        if "alterar_senha" in request.POST:
            pf = UserPasswordForm(request.user, request.POST)
            if pf.is_valid():
                u = request.user
                u.set_password(pf.cleaned_data["nova_senha"])
                u.save()
                messages.success(request, "Senha alterada! Faça login novamente.")
                return redirect("login")
            return render(
                request,
                self.template_name,
                {"profile_form": UserProfileForm(instance=request.user), "password_form": pf},
            )
        return redirect("perfil")


class ConfiguracoesIndexView(LoginRequiredMixin, TemplateView):
    template_name = "app/configuracoes/index.html"


class ConfiguracoesSistemaView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "app/configuracoes/sistema.html"
    raise_exception = True

    def test_func(self):
        return self.request.user.has_role("admin")


class UsuarioListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = User
    template_name = "app/configuracoes/usuarios.html"
    context_object_name = "usuarios"

    def test_func(self):
        return self.request.user.has_role("admin", "pastor")

    def get_queryset(self):
        return User.objects.order_by("nome")


class UsuarioCreateView(LoginRequiredMixin, UserPassesTestMixin, View):
    template_name = "app/configuracoes/novo_usuario.html"

    def test_func(self):
        return self.request.user.has_role("admin", "pastor")

    def get(self, request):
        return render(request, self.template_name, {"form": UserCreateForm()})

    def post(self, request):
        form = UserCreateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Usuário criado!")
            return redirect("configuracoes_usuarios")
        return render(request, self.template_name, {"form": form})


class UsuarioUpdateView(LoginRequiredMixin, UserPassesTestMixin, View):
    template_name = "app/configuracoes/editar_usuario.html"

    def test_func(self):
        return self.request.user.has_role("admin", "pastor")

    def get(self, request, pk):
        u = get_object_or_404(User, pk=pk)
        return render(request, self.template_name, {"usuario_obj": u, "form": UserAdminForm(instance=u)})

    def post(self, request, pk):
        u = get_object_or_404(User, pk=pk)
        form = UserAdminForm(request.POST, instance=u)
        if form.is_valid():
            form.save()
            messages.success(request, "Usuário atualizado!")
            return redirect("configuracoes_usuarios")
        return render(request, self.template_name, {"usuario_obj": u, "form": form})


class UsuarioDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = User
    template_name = "app/confirmar_exclusao.html"
    success_url = reverse_lazy("configuracoes_usuarios")

    def test_func(self):
        return self.request.user.is_superuser

    def form_valid(self, form):
        if self.object.pk == self.request.user.pk:
            messages.error(self.request, "Não é possível excluir o próprio usuário.")
            return redirect("configuracoes_usuarios")
        messages.success(self.request, "Usuário excluído.")
        return super().form_valid(form)
