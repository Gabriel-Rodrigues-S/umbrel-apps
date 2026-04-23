from django import forms

from church.models import Ministerio, MinisterioMembro, PequenoGrupo, PequenoGrupoMembro


class _B:
    def _style(self):
        for field in self.fields.values():
            w = field.widget
            cls = "form-select" if isinstance(w, forms.Select) else "form-control"
            w.attrs.setdefault("class", cls)


class MinisterioForm(_B, forms.ModelForm):
    class Meta:
        model = Ministerio
        fields = [
            "nome",
            "descricao",
            "lider",
            "vice_lider",
            "data_criacao",
            "status",
        ]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class MinisterioMembroForm(_B, forms.ModelForm):
    class Meta:
        model = MinisterioMembro
        fields = [
            "ministerio",
            "pessoa",
            "funcao",
            "data_entrada",
            "data_saida",
            "status",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class PequenoGrupoForm(_B, forms.ModelForm):
    class Meta:
        model = PequenoGrupo
        fields = [
            "nome",
            "descricao",
            "lider",
            "vice_lider",
            "anfitriao",
            "dia_reuniao",
            "horario_reuniao",
            "endereco",
            "cidade",
            "bairro",
            "data_criacao",
            "status",
        ]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class PequenoGrupoMembroForm(_B, forms.ModelForm):
    class Meta:
        model = PequenoGrupoMembro
        fields = ["grupo", "pessoa", "data_entrada", "data_saida", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
