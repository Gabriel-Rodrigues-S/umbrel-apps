from django import forms

from church.models import CategoriaFinanceira, LancamentoFinanceiro


class _B:
    def _style(self):
        for field in self.fields.values():
            w = field.widget
            cls = "form-select" if isinstance(w, forms.Select) else "form-control"
            w.attrs.setdefault("class", cls)


class LancamentoFinanceiroForm(_B, forms.ModelForm):
    class Meta:
        model = LancamentoFinanceiro
        fields = [
            "tipo",
            "categoria",
            "pessoa",
            "valor",
            "data_lancamento",
            "descricao",
            "metodo_pagamento",
            "comprovante",
        ]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
        self.fields["valor"].widget.attrs.setdefault("class", "form-control money")


class CategoriaFinanceiraForm(_B, forms.ModelForm):
    class Meta:
        model = CategoriaFinanceira
        fields = ["nome", "tipo", "descricao", "status"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
