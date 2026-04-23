from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

User = get_user_model()


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["nome", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", "form-control")


class UserPasswordForm(forms.Form):
    senha_atual = forms.CharField(
        label="Senha atual",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )
    nova_senha = forms.CharField(
        label="Nova senha",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )
    confirmar = forms.CharField(
        label="Confirmar nova senha",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        n1 = data.get("nova_senha")
        n2 = data.get("confirmar")
        if n1 and n2 and n1 != n2:
            self.add_error("confirmar", "As senhas não coincidem.")
        if self.user and not self.user.check_password(data.get("senha_atual", "")):
            self.add_error("senha_atual", "Senha atual incorreta.")
        if n1:
            try:
                validate_password(n1, user=self.user)
            except DjangoValidationError as exc:
                for message in exc.messages:
                    self.add_error("nova_senha", message)
        return data


class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["nome", "email", "nivel_acesso", "status", "is_staff", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, f in self.fields.items():
            if name in ("is_staff", "is_active"):
                f.widget.attrs.setdefault("class", "form-check-input")
            else:
                f.widget.attrs.setdefault("class", "form-control")


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = User
        fields = ["nome", "email", "nivel_acesso", "status", "is_staff", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, f in self.fields.items():
            if name in ("is_staff", "is_active"):
                f.widget.attrs.setdefault("class", "form-check-input")
            elif name != "password":
                f.widget.attrs.setdefault("class", "form-control")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user

    def clean_password(self):
        password = self.cleaned_data.get("password", "")
        candidate_user = self.instance if self.instance and self.instance.pk else User()
        candidate_user.email = self.cleaned_data.get("email", "")
        candidate_user.nome = self.cleaned_data.get("nome", "")
        try:
            validate_password(password, user=candidate_user)
        except DjangoValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return password
