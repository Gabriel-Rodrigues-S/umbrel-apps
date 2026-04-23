from django import forms

from church.models import ClasseAluno, ClasseEstudo, Discipulado


class _B:
    def _style(self):
        for field in self.fields.values():
            w = field.widget
            cls = "form-select" if isinstance(w, forms.Select) else "form-control"
            w.attrs.setdefault("class", cls)


class DiscipuladoForm(_B, forms.ModelForm):
    class Meta:
        model = Discipulado
        fields = [
            "discipulador",
            "discipulo",
            "data_inicio",
            "data_conclusao",
            "status",
            "observacoes",
        ]
        widgets = {"observacoes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class ClasseEstudoForm(_B, forms.ModelForm):
    class Meta:
        model = ClasseEstudo
        fields = [
            "nome",
            "descricao",
            "professor",
            "dia_semana",
            "horario",
            "local",
            "data_inicio",
            "data_fim",
            "status",
        ]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class ClasseAlunoForm(_B, forms.ModelForm):
    class Meta:
        model = ClasseAluno
        fields = [
            "classe",
            "pessoa",
            "data_inscricao",
            "data_conclusao",
            "status",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
