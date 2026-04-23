from django import forms

from church.models import (
    Certificado,
    Curso,
    CursoAula,
    CursoMatricula,
    CursoModulo,
    CursoNota,
    CursoPresenca,
)


class _B:
    def _style(self):
        for field in self.fields.values():
            w = field.widget
            cls = "form-select" if isinstance(w, forms.Select) else "form-control"
            w.attrs.setdefault("class", cls)


class CursoForm(_B, forms.ModelForm):
    class Meta:
        model = Curso
        fields = [
            "nome",
            "descricao",
            "instrutor",
            "carga_horaria",
            "data_inicio",
            "data_fim",
            "certificado_template",
            "status",
        ]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 2}),
            "certificado_template": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class CursoModuloForm(_B, forms.ModelForm):
    class Meta:
        model = CursoModulo
        fields = ["curso", "nome", "descricao", "ordem", "media_aprovacao"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class CursoAulaForm(_B, forms.ModelForm):
    class Meta:
        model = CursoAula
        fields = [
            "modulo",
            "titulo",
            "conteudo",
            "material_apoio",
            "video_url",
            "ordem",
        ]
        widgets = {"conteudo": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class CursoMatriculaForm(_B, forms.ModelForm):
    class Meta:
        model = CursoMatricula
        fields = [
            "curso",
            "pessoa",
            "data_matricula",
            "data_conclusao",
            "nota_final",
            "status",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class CursoPresencaForm(_B, forms.ModelForm):
    class Meta:
        model = CursoPresenca
        fields = ["aula", "matricula", "data_aula", "presente"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class CursoNotaForm(_B, forms.ModelForm):
    class Meta:
        model = CursoNota
        fields = ["modulo", "matricula", "nota", "data_avaliacao"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class CertificadoForm(_B, forms.ModelForm):
    class Meta:
        model = Certificado
        fields = [
            "matricula",
            "codigo_verificacao",
            "data_emissao",
            "arquivo_pdf",
            "enviado_email",
            "data_envio_email",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()
