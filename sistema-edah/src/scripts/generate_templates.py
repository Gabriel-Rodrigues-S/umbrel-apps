"""Gera templates mínimos app/*.html para todas as views (Bootstrap)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "templates" / "app"

LIST_SPECS = [
    ("membros/listar.html", "Membros da Igreja", "membros", "membros_cadastrar", "Novo Membro", [
        ("pessoa.nome", "Nome"),
        ("pessoa.email|default:'-'", "E-mail"),
        ("pessoa.celular|default:pessoa.telefone|default:'-'", "Telefone"),
        ("cargo|default:'-'", "Cargo/Função"),
        ("data_entrada|date:'d/m/Y'|default:'-'", "Data Entrada"),
        ("status", "Status"),
    ], "membros_visualizar", "membros_editar"),
    ("visitantes/listar.html", "Visitantes", "visitantes", "visitantes_cadastrar", "Novo Visitante", [
        ("pessoa.nome", "Nome"),
        ("pessoa.email|default:'-'", "E-mail"),
        ("data_ultima_visita|date:'d/m/Y'|default:'-'", "Última visita"),
        ("total_visitas", "Visitas"),
    ], "visitantes_visualizar", "visitantes_editar"),
    ("lideres/listar.html", "Líderes", "lideres", "lideres_cadastrar", "Novo Líder", [
        ("pessoa.nome", "Nome"),
        ("get_tipo_lideranca_display", "Tipo"),
        ("status", "Status"),
    ], "lideres_visualizar", "lideres_editar"),
    ("funcionarios/listar.html", "Funcionários", "funcionarios", "funcionarios_cadastrar", "Novo Funcionário", [
        ("pessoa.nome", "Nome"),
        ("cargo", "Cargo"),
        ("status", "Status"),
    ], "funcionarios_visualizar", "funcionarios_editar"),
    ("familias/listar.html", "Famílias", "familias", "familias_cadastrar", "Nova Família", [
        ("nome_familia", "Nome"),
        ("responsavel", "Responsável"),
    ], "familias_visualizar", "familias_editar"),
    ("discipulado/listar.html", "Discipulado", "itens", None, None, [
        ("discipulador", "Discipulador"),
        ("discipulo", "Discípulo"),
        ("status", "Status"),
    ], "discipulado_visualizar", "discipulado_editar"),
    ("classes/listar.html", "Classes de Estudo", "classes", "classes_cadastrar", "Nova Classe", [
        ("nome", "Nome"),
        ("status", "Status"),
    ], "classes_visualizar", "classes_editar"),
    ("pequenos_grupos/listar.html", "Pequenos Grupos", "grupos", "pequenos_grupos_cadastrar", "Novo Grupo", [
        ("nome", "Nome"),
        ("status", "Status"),
    ], "pequenos_grupos_visualizar", "pequenos_grupos_editar"),
    ("ministerios/listar.html", "Ministérios", "ministerios", "ministerios_cadastrar", "Novo Ministério", [
        ("nome", "Nome"),
        ("status", "Status"),
    ], "ministerios_visualizar", "ministerios_editar"),
    ("financeiro/lancamentos.html", "Lançamentos Financeiros", "lancamentos", "financeiro_lancamento_novo", "Novo Lançamento", [
        ("get_tipo_display", "Tipo"),
        ("valor", "Valor"),
        ("data_lancamento|date:'d/m/Y'", "Data"),
    ], None, "financeiro_lancamento_editar"),
    ("financeiro/dizimos.html", "Dízimos", "lancamentos", "financeiro_lancamento_novo", "Novo", [
        ("valor", "Valor"),
        ("data_lancamento|date:'d/m/Y'", "Data"),
        ("pessoa", "Pessoa"),
    ], None, None),
    ("financeiro/ofertas.html", "Ofertas", "lancamentos", "financeiro_lancamento_novo", "Novo", [
        ("valor", "Valor"),
        ("data_lancamento|date:'d/m/Y'", "Data"),
    ], None, None),
    ("cursos/listar.html", "Cursos", "cursos", "cursos_cadastrar", "Novo Curso", [
        ("nome", "Nome"),
        ("status", "Status"),
    ], "cursos_visualizar", "cursos_editar"),
    ("cursos/modulos.html", "Módulos dos Cursos", "modulos", "cursos_modulos_novo", "Novo Módulo", [
        ("curso", "Curso"),
        ("nome", "Módulo"),
    ], None, None),
    ("cursos/aulas.html", "Aulas", "aulas", "cursos_aulas_novo", "Nova Aula", [
        ("modulo", "Módulo"),
        ("titulo", "Título"),
    ], None, None),
    ("cursos/matriculas.html", "Matrículas", "matriculas", "cursos_matriculas_novo", "Nova Matrícula", [
        ("curso", "Curso"),
        ("pessoa", "Pessoa"),
        ("status", "Status"),
    ], "cursos_matricula_detalhe", "cursos_matricula_editar"),
    ("cursos/presencas.html", "Presenças", "presencas", "cursos_presencas_novo", "Registrar", [
        ("aula", "Aula"),
        ("matricula", "Matrícula"),
        ("data_aula|date:'d/m/Y'", "Data"),
        ("presente", "Presente"),
    ], None, None),
    ("cursos/notas.html", "Notas", "notas", "cursos_notas_novo", "Nova Nota", [
        ("modulo", "Módulo"),
        ("matricula", "Matrícula"),
        ("nota", "Nota"),
    ], None, None),
    ("cursos/certificados.html", "Certificados", "certificados", "cursos_certificados_novo", "Novo", [
        ("matricula", "Matrícula"),
        ("codigo_verificacao", "Código"),
        ("data_emissao|date:'d/m/Y'", "Emissão"),
    ], "cursos_certificado_visualizar", "cursos_certificado_editar"),
    ("eventos/listar.html", "Eventos", "eventos", "eventos_cadastrar", "Novo Evento", [
        ("nome", "Nome"),
        ("data_inicio|date:'d/m/Y H:i'", "Início"),
        ("status", "Status"),
    ], "eventos_visualizar", "eventos_editar"),
    ("eventos/responsaveis.html", "Responsáveis por Evento", "responsaveis", "eventos_responsaveis_novo", "Adicionar", [
        ("evento", "Evento"),
        ("pessoa", "Pessoa"),
        ("funcao", "Função"),
    ], None, None),
    ("eventos/inscricoes.html", "Inscrições em Eventos", "inscricoes", "eventos_inscricoes_novo", "Nova Inscrição", [
        ("evento", "Evento"),
        ("pessoa", "Pessoa"),
        ("pago", "Pago"),
    ], None, "eventos_inscricao_editar"),
    ("noticias/listar.html", "Notícias", "noticias", "noticias_cadastrar", "Nova Notícia", [
        ("titulo", "Título"),
        ("status", "Status"),
    ], "noticias_visualizar", "noticias_editar"),
    ("pedidos_oracao/listar.html", "Pedidos de Oração", "pedidos", "pedidos_oracao_cadastrar", "Novo Pedido", [
        ("nome", "Nome"),
        ("status", "Status"),
        ("data_pedido|date:'d/m/Y H:i'", "Data"),
    ], "pedidos_oracao_visualizar", "pedidos_oracao_editar"),
    ("galeria/listar.html", "Galerias", "galerias", "galeria_cadastrar", "Nova Galeria", [
        ("titulo", "Título"),
        ("data_criacao|date:'d/m/Y'", "Criada em"),
    ], "galeria_visualizar", "galeria_editar"),
    ("galeria/fotos.html", "Fotos da Galeria", "fotos", "galeria_fotos_novo", "Adicionar Foto", [
        ("galeria", "Galeria"),
        ("arquivo", "Arquivo"),
    ], None, None),
    ("mensagens/listar.html", "Mensagens", "mensagens", "mensagens_nova", "Nova Mensagem", [
        ("remetente", "De"),
        ("assunto", "Assunto"),
        ("data_envio|date:'d/m/Y H:i'", "Data"),
    ], "mensagens_visualizar", None),
    ("financeiro/categorias.html", "Categorias Financeiras", "categorias", None, None, [
        ("nome", "Nome"),
        ("tipo", "Tipo"),
        ("status", "Status"),
    ], None, None),
    ("classes/alunos.html", "Alunos nas Classes", "alunos", "classes_alunos_novo", "Vincular Aluno", [
        ("classe", "Classe"),
        ("pessoa", "Pessoa"),
        ("status", "Status"),
    ], None, None),
    ("pequenos_grupos/membros.html", "Membros de Pequenos Grupos", "vinculos", "pequenos_grupos_membros_novo", "Vincular", [
        ("grupo", "Grupo"),
        ("pessoa", "Pessoa"),
        ("status", "Status"),
    ], None, None),
    ("ministerios/membros.html", "Membros de Ministérios", "vinculos", "ministerios_membros_novo", "Vincular", [
        ("ministerio", "Ministério"),
        ("pessoa", "Pessoa"),
        ("funcao", "Função"),
    ], None, None),
    ("familias/membros.html", "Membros por Família", "vinculos", "familias_membros_novo", "Vincular", [
        ("familia", "Família"),
        ("pessoa", "Pessoa"),
        ("parentesco", "Parentesco"),
    ], None, None),
]

DETAIL = """{% extends "app/base.html" %}
{% block title %}{{ titulo }} - SYS_EDAH{% endblock %}
{% block content %}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
  <h1 class="h2"><i class="fas fa-eye"></i> {{ titulo }}</h1>
  <a href="{{ back_url }}" class="btn btn-secondary"><i class="fas fa-arrow-left"></i> Voltar</a>
</div>
<div class="card shadow mb-4"><div class="card-body">{{ body|safe }}</div></div>
{% endblock %}
"""


def list_tpl(path, h1, iter_name, add_url, add_label, cols, view_url, edit_url):
    head = "".join(f"<th>{c[1]}</th>" for c in cols)
    cells = []
    for field, _ in cols:
        if "|" in field:
            base, filters = field.split("|", 1)
            cells.append(f"{{% with v=o.{base} %}}{{{{ v|{filters} }}}}{{% endwith %}}")
        else:
            cells.append(f"{{{{ o.{field} }}}}")
    row = "<td>" + "</td><td>".join(cells) + "</td>"
    actions = "<div class=\"btn-group btn-group-sm\">"
    if view_url:
        actions += f'<a href="{{% url "{view_url}" o.pk %}}" class="btn btn-info"><i class="fas fa-eye"></i></a>'
    if edit_url:
        actions += f'<a href="{{% url "{edit_url}" o.pk %}}" class="btn btn-warning"><i class="fas fa-edit"></i></a>'
    actions += "</div>"
    add_btn = ""
    if add_url:
        add_btn = f'<a href="{{% url "{add_url}" %}}" class="btn btn-primary"><i class="fas fa-plus"></i> {add_label}</a>'
    return f"""{{% extends "app/base.html" %}}
{{% block title %}}{h1} - SYS_EDAH{{% endblock %}}
{{% block content %}}
<div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
  <h1 class="h2"><i class="fas fa-list"></i> {h1}</h1>
  <div>{add_btn}</div>
</div>
<div class="card shadow mb-4">
  <div class="card-header py-3"><h6 class="m-0 font-weight-bold text-primary">Lista</h6></div>
  <div class="card-body">
    <div class="table-responsive">
      <table class="table table-bordered datatable" width="100%">
        <thead><tr>{head}<th>Ações</th></tr></thead>
        <tbody>
        {{% for o in {iter_name} %}}
        <tr>{row}<td>{actions}</td></tr>
        {{% empty %}}
        <tr><td colspan="{len(cols)+1}" class="text-center text-muted">Nenhum registro.</td></tr>
        {{% endfor %}}
        </tbody>
      </table>
    </div>
  </div>
</div>
{{% endblock %}}
"""


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    for spec in LIST_SPECS:
        if len(spec) == 8:
            path, h1, it, au, al, cols, vu, eu = spec
            content = list_tpl(path, h1, it, au, al, cols, vu, eu)
        else:
            continue
        p = ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        print("wrote", p)


if __name__ == "__main__":
    main()
