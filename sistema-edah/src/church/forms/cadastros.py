from django import forms

from church.models import (
    Casal,
    Familia,
    FamiliaMembro,
    Funcionario,
    Igreja,
    Lider,
    Membro,
    Parentesco,
    Pessoa,
    StatusFuncionario,
    StatusLider,
    StatusMembro,
    TipoContrato,
    TipoLideranca,
    TipoPessoa,
    Visitante,
)


class _BootstrapMixin:
    def _style(self):
        for name, field in self.fields.items():
            w = field.widget
            cls = "form-select" if isinstance(w, forms.Select) else "form-control"
            w.attrs.setdefault("class", cls)


class PessoaForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Pessoa
        fields = [
            "nome",
            "genero",
            "data_nascimento",
            "profissao",
            "estado_civil",
            "telefone",
            "celular",
            "email",
            "cep",
            "endereco",
            "numero",
            "complemento",
            "bairro",
            "cidade",
            "estado",
            "como_conheceu_igreja",
            "observacoes",
            "status_personalizado",
        ]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "como_conheceu_igreja": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "observacoes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
        self.fields["telefone"].widget.attrs.setdefault("class", "form-control phone")
        self.fields["celular"].widget.attrs.setdefault("class", "form-control celular")
        self.fields["cep"].widget.attrs.setdefault("class", "form-control cep")


class MembroForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Membro
        fields = [
            "data_batismo",
            "data_conversao",
            "data_entrada",
            "cargo",
            "funcao",
            "status",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class VisitanteForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Visitante
        fields = [
            "data_primeira_visita",
            "data_ultima_visita",
            "total_visitas",
            "convertido_membro",
            "data_conversao_membro",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class LiderForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Lider
        fields = ["tipo_lideranca", "data_inicio", "data_fim", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class FuncionarioForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Funcionario
        fields = [
            "cargo",
            "data_admissao",
            "data_demissao",
            "salario",
            "tipo_contrato",
            "status",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class FamiliaForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Familia
        fields = ["nome_familia", "responsavel"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
        self.fields["responsavel"].queryset = Pessoa.objects.all().order_by("nome")


class FamiliaMembroForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = FamiliaMembro
        fields = ["familia", "pessoa", "parentesco"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
        self.fields["pessoa"].queryset = Pessoa.objects.all().order_by("nome")
        self.fields["familia"].queryset = Familia.objects.all().order_by("nome_familia")


class CasalForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Casal
        fields = ["esposo", "esposa", "data_casamento", "familia"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
        self.fields["esposo"].queryset = Pessoa.objects.all().order_by("nome")
        self.fields["esposa"].queryset = Pessoa.objects.all().order_by("nome")


class IgrejaForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Igreja
        fields = [
            "nome",
            "cnpj",
            "endereco",
            "bairro",
            "cidade",
            "estado",
            "cep",
            "telefone",
            "email",
            "site",
            "pastor_presidente",
            "data_fundacao",
        ]
        widgets = {
            "endereco": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
        self.fields["telefone"].widget.attrs.setdefault("class", "form-control phone")
        self.fields["cep"].widget.attrs.setdefault("class", "form-control cep")
