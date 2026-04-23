"""Gera templates de listagem simples (objeto + links) para views restantes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "templates" / "app"

# path, title, iter_name, add_name, add_label, detail_name, edit_name, delete_name (optional)
DATA = [
    ("visitantes/listar.html", "Visitantes", "visitantes", "visitantes_cadastrar", "Novo Visitante", "visitantes_visualizar", "visitantes_editar", None, "visitantes_converter"),
    ("lideres/listar.html", "Líderes", "lideres", "lideres_cadastrar", "Novo Líder", "lideres_visualizar", "lideres_editar", None, None),
    ("funcionarios/listar.html", "Funcionários", "funcionarios", "funcionarios_cadastrar", "Novo Funcionário", "funcionarios_visualizar", "funcionarios_editar", None, None),
    ("familias/listar.html", "Famílias", "familias", "familias_cadastrar", "Nova Família", "familias_visualizar", "familias_editar", None, None),
    ("discipulado/listar.html", "Discipulados", "itens", "discipulado_cadastrar", "Novo", "discipulado_visualizar", "discipulado_editar", "discipulado_excluir", None),
    ("classes/listar.html", "Classes de Estudo", "classes", "classes_cadastrar", "Nova Classe", "classes_visualizar", "classes_editar", "classes_excluir", None),
    ("pequenos_grupos/listar.html", "Pequenos Grupos", "grupos", "pequenos_grupos_cadastrar", "Novo Grupo", "pequenos_grupos_visualizar", "pequenos_grupos_editar", "pequenos_grupos_excluir", None),
    ("ministerios/listar.html", "Ministérios", "ministerios", "ministerios_cadastrar", "Novo Ministério", "ministerios_visualizar", "ministerios_editar", "ministerios_excluir", None),
    ("financeiro/lancamentos.html", "Lançamentos Financeiros", "lancamentos", "financeiro_lancamento_novo", "Novo Lançamento", None, "financeiro_lancamento_editar", "financeiro_lancamento_excluir", None),
    ("financeiro/dizimos.html", "Dízimos", "lancamentos", "financeiro_lancamento_novo", "Novo", None, "financeiro_lancamento_editar", None, None),
    ("financeiro/ofertas.html", "Ofertas", "lancamentos", "financeiro_lancamento_novo", "Novo", None, "financeiro_lancamento_editar", None, None),
    ("financeiro/categorias.html", "Categorias Financeiras", "categorias", None, None, None, None, None, None),
    ("cursos/listar.html", "Cursos", "cursos", "cursos_cadastrar", "Novo Curso", "cursos_visualizar", "cursos_editar", "cursos_excluir", None),
    ("cursos/modulos.html", "Módulos", "modulos", "cursos_modulos_novo", "Novo Módulo", None, None, None, None),
    ("cursos/aulas.html", "Aulas", "aulas", "cursos_aulas_novo", "Nova Aula", None, None, None, None),
    ("cursos/matriculas.html", "Matrículas", "matriculas", "cursos_matriculas_novo", "Nova Matrícula", "cursos_matricula_detalhe", "cursos_matricula_editar", None, None),
    ("cursos/presencas.html", "Presenças", "presencas", "cursos_presencas_novo", "Registrar", None, None, None, None),
    ("cursos/notas.html", "Notas", "notas", "cursos_notas_novo", "Nova Nota", None, None, None, None),
    ("cursos/certificados.html", "Certificados", "certificados", "cursos_certificados_novo", "Novo", "cursos_certificado_visualizar", "cursos_certificado_editar", None, None),
    ("eventos/listar.html", "Eventos", "eventos", "eventos_cadastrar", "Novo Evento", "eventos_visualizar", "eventos_editar", "eventos_excluir", None),
    ("eventos/responsaveis.html", "Responsáveis", "responsaveis", "eventos_responsaveis_novo", "Adicionar", None, None, None, None),
    ("eventos/inscricoes.html", "Inscrições", "inscricoes", "eventos_inscricoes_novo", "Nova Inscrição", None, "eventos_inscricao_editar", None, None),
    ("noticias/listar.html", "Notícias", "noticias", "noticias_cadastrar", "Nova", "noticias_visualizar", "noticias_editar", "noticias_excluir", None),
    ("pedidos_oracao/listar.html", "Pedidos de Oração", "pedidos", "pedidos_oracao_cadastrar", "Novo", "pedidos_oracao_visualizar", "pedidos_oracao_editar", "pedidos_oracao_excluir", None),
    ("galeria/listar.html", "Galerias", "galerias", "galeria_cadastrar", "Nova", "galeria_visualizar", "galeria_editar", "galeria_excluir", None),
    ("galeria/fotos.html", "Fotos", "fotos", "galeria_fotos_novo", "Adicionar", None, None, None, None),
    ("mensagens/listar.html", "Mensagens", "mensagens", "mensagens_nova", "Nova", "mensagens_visualizar", None, "mensagens_excluir", None),
    ("classes/alunos.html", "Alunos (classes)", "alunos", "classes_alunos_novo", "Vincular", None, None, None, None),
    ("pequenos_grupos/membros.html", "Membros de grupos", "vinculos", "pequenos_grupos_membros_novo", "Vincular", None, None, None, None),
    ("ministerios/membros.html", "Membros de ministérios", "vinculos", "ministerios_membros_novo", "Vincular", None, None, None, None),
    ("familias/membros.html", "Membros por família", "vinculos", "familias_membros_novo", "Vincular", None, None, None, None),
]


def tpl(path, title, it, add_n, add_l, det, edit, delete, extra):
    add = ""
    if add_n:
        add = f'<a href="{{% url \'{add_n}\' %}}" class="btn btn-primary"><i class="fas fa-plus"></i> {add_l}</a>'

    def btn(url_name, cls, icon, label):
        return f'<a href="{{% url \'{url_name}\' o.pk %}}" class="btn btn-sm {cls}" title="{label}"><i class="fas {icon}"></i></a>'

    actions = []
    if det:
        actions.append(btn(det, "btn-info", "fa-eye", "Ver"))
    if edit:
        actions.append(btn(edit, "btn-warning", "fa-edit", "Editar"))
    if delete:
        actions.append(btn(delete, "btn-danger", "fa-trash", "Excluir"))
    if extra == "visitantes_converter":
        actions.append(
            '<a href="{% url \'visitantes_converter\' o.pk %}" class="btn btn-sm btn-success" title="Converter"><i class="fas fa-user-check"></i></a>'
        )
    act_html = " ".join(actions)

    return f"""{{% extends "app/base.html" %}}
{{% block title %}}{title} - SYS_EDAH{{% endblock %}}
{{% block content %}}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
  <h1 class="h2"><i class="fas fa-list"></i> {title}</h1>
  <div>{add}</div>
</div>
<div class="card shadow mb-4">
  <div class="card-header py-3"><h6 class="m-0 font-weight-bold text-primary">Lista</h6></div>
  <div class="card-body">
    <div class="table-responsive">
      <table class="table table-bordered datatable" width="100%">
        <thead><tr><th>#</th><th>Descrição</th><th>Ações</th></tr></thead>
        <tbody>
        {{% for o in {it} %}}
        <tr>
          <td>{{{{ o.pk }}}}</td>
          <td>{{{{ o }}}}</td>
          <td><div class="btn-group btn-group-sm">{act_html}</div></td>
        </tr>
        {{% empty %}}
        <tr><td colspan="3" class="text-center text-muted">Nenhum registro.</td></tr>
        {{% endfor %}}
        </tbody>
      </table>
    </div>
  </div>
</div>
{{% endblock %}}
"""


def main():
    for row in DATA:
        path = ROOT / row[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tpl(*row), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
