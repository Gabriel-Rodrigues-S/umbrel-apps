from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "templates"

PAIRS = [
    ("app/discipulado/cadastrar.html", "Novo Discipulado"),
    ("app/discipulado/editar.html", "Editar Discipulado"),
    ("app/classes/cadastrar.html", "Nova Classe de Estudo"),
    ("app/classes/editar.html", "Editar Classe"),
    ("app/classes/cadastrar_aluno.html", "Vincular Aluno à Classe"),
    ("app/pequenos_grupos/cadastrar.html", "Novo Pequeno Grupo"),
    ("app/pequenos_grupos/editar.html", "Editar Pequeno Grupo"),
    ("app/pequenos_grupos/vincular_membro.html", "Vincular Membro ao Grupo"),
    ("app/ministerios/cadastrar.html", "Novo Ministério"),
    ("app/ministerios/editar.html", "Editar Ministério"),
    ("app/ministerios/vincular_membro.html", "Vincular Membro ao Ministério"),
    ("app/familias/cadastrar.html", "Nova Família"),
    ("app/familias/editar.html", "Editar Família"),
    ("app/familias/vincular_membro.html", "Vincular Membro à Família"),
    ("app/familias/cadastrar_casal.html", "Novo Casal"),
    ("app/igreja/editar.html", "Dados da Igreja"),
    ("app/financeiro/novo_lancamento.html", "Novo Lançamento"),
    ("app/financeiro/editar_lancamento.html", "Editar Lançamento"),
    ("app/cursos/cadastrar.html", "Novo Curso"),
    ("app/cursos/editar.html", "Editar Curso"),
    ("app/cursos/cadastrar_modulo.html", "Novo Módulo"),
    ("app/cursos/cadastrar_aula.html", "Nova Aula"),
    ("app/cursos/nova_matricula.html", "Nova Matrícula"),
    ("app/cursos/editar_matricula.html", "Editar Matrícula"),
    ("app/cursos/registrar_presenca.html", "Registrar Presença"),
    ("app/cursos/registrar_nota.html", "Registrar Nota"),
    ("app/cursos/gerar_certificado.html", "Gerar Certificado"),
    ("app/cursos/editar_certificado.html", "Editar Certificado"),
    ("app/eventos/cadastrar.html", "Novo Evento"),
    ("app/eventos/editar.html", "Editar Evento"),
    ("app/eventos/cadastrar_responsavel.html", "Novo Responsável"),
    ("app/eventos/nova_inscricao.html", "Nova Inscrição"),
    ("app/eventos/editar_inscricao.html", "Editar Inscrição"),
    ("app/noticias/cadastrar.html", "Nova Notícia"),
    ("app/noticias/editar.html", "Editar Notícia"),
    ("app/pedidos_oracao/cadastrar.html", "Novo Pedido de Oração"),
    ("app/pedidos_oracao/editar.html", "Editar Pedido"),
    ("app/galeria/cadastrar.html", "Nova Galeria"),
    ("app/galeria/editar.html", "Editar Galeria"),
    ("app/galeria/adicionar_foto.html", "Adicionar Foto"),
    ("app/configuracoes/novo_usuario.html", "Novo Usuário"),
    ("app/configuracoes/editar_usuario.html", "Editar Usuário"),
    ("app/mensagens/nova.html", "Nova Mensagem"),
]


def main():
    for rel, title in PAIRS:
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            f'{{% extends "app/form_padrao.html" %}}\n{{% block page_h1 %}}{title}{{% endblock %}}\n',
            encoding="utf-8",
        )
        print(p)


if __name__ == "__main__":
    main()
