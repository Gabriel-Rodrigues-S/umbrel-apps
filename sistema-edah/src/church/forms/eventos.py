from django import forms

from church.models import Evento, EventoInscricao, EventoResponsavel


class _B:
    def _style(self):
        for field in self.fields.values():
            w = field.widget
            cls = "form-select" if isinstance(w, forms.Select) else "form-control"
            w.attrs.setdefault("class", cls)


class EventoForm(_B, forms.ModelForm):
    class Meta:
        model = Evento
        fields = [
            "nome",
            "descricao",
            "tipo_evento",
            "data_inicio",
            "data_fim",
            "local",
            "capacidade_maxima",
            "valor_inscricao",
            "imagem_capa",
            "publicar_site",
            "publicar_app",
            "status",
        ]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class EventoResponsavelForm(_B, forms.ModelForm):
    class Meta:
        model = EventoResponsavel
        fields = ["evento", "pessoa", "funcao", "permissoes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class EventoInscricaoForm(_B, forms.ModelForm):
    class Meta:
        model = EventoInscricao
        fields = [
            "evento",
            "pessoa",
            "valor_pago",
            "pago",
            "presente",
            "observacoes",
        ]
        widgets = {"observacoes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
