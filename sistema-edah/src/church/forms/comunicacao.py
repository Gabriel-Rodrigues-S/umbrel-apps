from django import forms
from django.contrib.auth import get_user_model

from church.models import Galeria, GaleriaFoto, Mensagem, Noticia, PedidoOracao

User = get_user_model()


class _B:
    def _style(self):
        for field in self.fields.values():
            w = field.widget
            cls = "form-select" if isinstance(w, forms.Select) else "form-control"
            w.attrs.setdefault("class", cls)


class NoticiaForm(_B, forms.ModelForm):
    class Meta:
        model = Noticia
        fields = [
            "titulo",
            "conteudo",
            "imagem",
            "data_publicacao",
            "publicar_site",
            "publicar_app",
            "status",
        ]
        widgets = {"conteudo": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class PedidoOracaoForm(_B, forms.ModelForm):
    class Meta:
        model = PedidoOracao
        fields = [
            "pessoa",
            "nome",
            "email",
            "telefone",
            "pedido",
            "anonimo",
            "status",
        ]
        widgets = {"pedido": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class GaleriaForm(_B, forms.ModelForm):
    class Meta:
        model = Galeria
        fields = [
            "titulo",
            "descricao",
            "evento",
            "data_evento",
            "capa",
            "publicar_app",
        ]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class GaleriaFotoForm(_B, forms.ModelForm):
    class Meta:
        model = GaleriaFoto
        fields = ["galeria", "arquivo", "legenda", "ordem"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class MensagemForm(_B, forms.ModelForm):
    class Meta:
        model = Mensagem
        fields = ["destinatario", "assunto", "mensagem"]
        widgets = {"mensagem": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
        qs = User.objects.filter(is_active=True).order_by("nome")
        if user:
            qs = qs.exclude(pk=user.pk)
        self.fields["destinatario"].queryset = qs
