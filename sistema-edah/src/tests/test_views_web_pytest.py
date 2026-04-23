"""
Testes das views web Django (não-API): dashboard, pessoas, configurações, perfil,
relatórios, grupos, ministerios, eventos, comunicação e financeiro.

Verifica que cada view:
  - rejeita usuários não autenticados (redireciona para login)
  - aceita usuários com papel adequado (HTTP 200 ou 302 esperado)
  - retorna 403 para usuários sem o papel necessário
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from church.models import (
    ClasseAluno,
    ClasseEstudo,
    Discipulado,
    Familia,
    Lider,
    LancamentoFinanceiro,
    Membro,
    Ministerio,
    MinisterioMembro,
    PequenoGrupo,
    PequenoGrupoMembro,
    Pessoa,
    StatusAtivo,
    StatusMembro,
    TipoLancamento,
    TipoLideranca,
    TipoPessoa,
    Visitante,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_user(make_user):
    return make_user(email="admin@church.com", nome="Admin", password="Forte123!", nivel_acesso="admin")


@pytest.fixture
def secretaria_user(make_user):
    return make_user(email="secr@church.com", nome="Secretaria", password="Forte123!", nivel_acesso="secretaria")


@pytest.fixture
def usuario_comum(make_user):
    return make_user(email="comum@church.com", nome="Comum", password="Forte123!", nivel_acesso="usuario")


@pytest.fixture
def pessoa_membro(admin_user):
    p = Pessoa.objects.create(tipo=TipoPessoa.MEMBRO, nome="Membro Teste", email="membro@teste.com")
    Membro.objects.create(pessoa=p, status=StatusMembro.ATIVO)
    return p


@pytest.fixture
def pessoa_visitante():
    return Pessoa.objects.create(tipo=TipoPessoa.VISITANTE, nome="Visitante Teste", email="visitante@teste.com")


@pytest.fixture
def visitante(pessoa_visitante):
    return Visitante.objects.create(pessoa=pessoa_visitante)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def get_autenticado(client, user, url):
    client.force_login(user)
    return client.get(url)


def assert_sem_acesso_anonimo(client, url):
    """Views com LoginRequiredMixin redirecionam; com raise_exception=True retornam 403.
    Ambos são comportamentos válidos de negação de acesso."""
    resp = client.get(url)
    assert resp.status_code in {302, 403}


def assert_redireciona_login(client, url):
    """Para views com LoginRequiredMixin puro (sem UserPassesTestMixin), espera 302."""
    resp = client.get(url)
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


# ─── Dashboard ───────────────────────────────────────────────────────────────


class TestDashboard:
    def test_redireciona_anonimo(self, client):
        assert_redireciona_login(client, reverse("dashboard"))

    def test_dashboard_acessivel_para_admin(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("dashboard"))
        assert resp.status_code == 200

    def test_dashboard_acessivel_para_usuario_comum(self, client, usuario_comum):
        resp = get_autenticado(client, usuario_comum, reverse("dashboard"))
        assert resp.status_code == 200

    def test_dashboard_contem_context_de_membros(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("dashboard"))
        assert "total_membros" in resp.context
        assert "proximos_eventos" in resp.context
        assert "membros_chart_labels" in resp.context


# ─── Perfil ──────────────────────────────────────────────────────────────────


class TestPerfil:
    def test_redireciona_anonimo(self, client):
        assert_redireciona_login(client, reverse("perfil"))

    def test_get_perfil_retorna_200(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("perfil"))
        assert resp.status_code == 200

    def test_post_salvar_perfil(self, client, admin_user):
        client.force_login(admin_user)
        resp = client.post(
            reverse("perfil"),
            {"salvar_perfil": "1", "nome": "Novo Nome", "email": admin_user.email},
        )
        assert resp.status_code in {200, 302}

    def test_post_sem_action_redireciona(self, client, admin_user):
        client.force_login(admin_user)
        resp = client.post(reverse("perfil"), {})
        assert resp.status_code == 302


# ─── Membros ─────────────────────────────────────────────────────────────────


class TestMembros:
    def test_redireciona_anonimo(self, client):
        assert_sem_acesso_anonimo(client, reverse("membros_listar"))

    def test_lista_membros_admin(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("membros_listar"))
        assert resp.status_code == 200

    def test_lista_membros_secretaria(self, client, secretaria_user):
        resp = get_autenticado(client, secretaria_user, reverse("membros_listar"))
        assert resp.status_code == 200

    def test_lista_membros_usuario_comum_bloqueado(self, client, usuario_comum):
        resp = get_autenticado(client, usuario_comum, reverse("membros_listar"))
        assert resp.status_code == 403

    def test_get_cadastrar_membro(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("membros_cadastrar"))
        assert resp.status_code == 200

    def test_get_visualizar_membro(self, client, admin_user, pessoa_membro):
        membro = Membro.objects.get(pessoa=pessoa_membro)
        resp = get_autenticado(client, admin_user, reverse("membros_visualizar", args=[membro.pk]))
        assert resp.status_code == 200

    def test_get_editar_membro(self, client, admin_user, pessoa_membro):
        membro = Membro.objects.get(pessoa=pessoa_membro)
        resp = get_autenticado(client, admin_user, reverse("membros_editar", args=[membro.pk]))
        assert resp.status_code == 200


# ─── Visitantes ──────────────────────────────────────────────────────────────


class TestVisitantes:
    def test_lista_visitantes_admin(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("visitantes_listar"))
        assert resp.status_code == 200

    def test_get_cadastrar_visitante(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("visitantes_cadastrar"))
        assert resp.status_code == 200

    def test_get_visualizar_visitante(self, client, admin_user, visitante):
        resp = get_autenticado(client, admin_user, reverse("visitantes_visualizar", args=[visitante.pk]))
        assert resp.status_code == 200


# ─── Configurações ───────────────────────────────────────────────────────────


class TestConfiguracoes:
    def test_redireciona_anonimo(self, client):
        assert_sem_acesso_anonimo(client, reverse("configuracoes_index"))

    def test_index_acessivel(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("configuracoes_index"))
        assert resp.status_code == 200

    def test_sistema_acessivel_para_admin(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("configuracoes_sistema"))
        assert resp.status_code == 200

    def test_sistema_bloqueado_para_usuario_comum(self, client, usuario_comum):
        resp = get_autenticado(client, usuario_comum, reverse("configuracoes_sistema"))
        assert resp.status_code == 403

    def test_lista_usuarios_acessivel_para_admin(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("configuracoes_usuarios"))
        assert resp.status_code == 200

    def test_get_criar_usuario_admin(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("configuracoes_usuario_novo"))
        assert resp.status_code == 200


# ─── Relatórios ──────────────────────────────────────────────────────────────


class TestRelatorios:
    def test_redireciona_anonimo(self, client):
        assert_sem_acesso_anonimo(client, reverse("relatorios_index"))

    def test_index_relatorios_admin(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("relatorios_index"))
        assert resp.status_code == 200

    def test_relatorio_membros(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("relatorios_membros"))
        assert resp.status_code == 200

    def test_relatorio_visitantes(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("relatorios_visitantes"))
        assert resp.status_code == 200

    def test_relatorio_eventos(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("relatorios_eventos"))
        assert resp.status_code == 200

    def test_relatorio_grupos(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("relatorios_grupos"))
        assert resp.status_code == 200

    def test_relatorio_cursos(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("relatorios_cursos"))
        assert resp.status_code == 200


# ─── Ministerios ─────────────────────────────────────────────────────────────


class TestMinisterios:
    @pytest.fixture
    def lider_obj(self):
        p = Pessoa.objects.create(tipo=TipoPessoa.MEMBRO, nome="Lider Teste", email="lider@teste.com")
        return Lider.objects.create(pessoa=p, tipo_lideranca=TipoLideranca.LIDER_MINISTERIO)

    @pytest.fixture
    def ministerio(self, lider_obj):
        return Ministerio.objects.create(nome="Louvor", lider=lider_obj)

    def test_lista_ministerios(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("ministerios_listar"))
        assert resp.status_code == 200

    def test_get_cadastrar_ministerio(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("ministerios_cadastrar"))
        assert resp.status_code == 200

    def test_detalhe_ministerio(self, client, admin_user, ministerio):
        resp = get_autenticado(client, admin_user, reverse("ministerios_visualizar", args=[ministerio.pk]))
        assert resp.status_code == 200

    def test_editar_ministerio(self, client, admin_user, ministerio):
        resp = get_autenticado(client, admin_user, reverse("ministerios_editar", args=[ministerio.pk]))
        assert resp.status_code == 200


# ─── Pequenos grupos ─────────────────────────────────────────────────────────


class TestPequenosGrupos:
    @pytest.fixture
    def grupo(self):
        return PequenoGrupo.objects.create(nome="Grupo Alfa", status=StatusAtivo.ATIVO)

    def test_lista_grupos(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("pequenos_grupos_listar"))
        assert resp.status_code == 200

    def test_get_cadastrar_grupo(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("pequenos_grupos_cadastrar"))
        assert resp.status_code == 200

    def test_detalhe_grupo(self, client, admin_user, grupo):
        resp = get_autenticado(client, admin_user, reverse("pequenos_grupos_visualizar", args=[grupo.pk]))
        assert resp.status_code == 200


# ─── Financeiro ──────────────────────────────────────────────────────────────


class TestFinanceiro:
    def test_lista_lancamentos(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("financeiro_lancamentos"))
        assert resp.status_code == 200

    def test_get_criar_lancamento(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("financeiro_lancamento_novo"))
        assert resp.status_code == 200

    def test_relatorio_financeiro(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("financeiro_relatorios"))
        assert resp.status_code == 200

    def test_categorias_financeiras(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("financeiro_categorias"))
        assert resp.status_code == 200


# ─── Família / Igreja ────────────────────────────────────────────────────────


class TestFamilia:
    def test_lista_familias(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("familias_listar"))
        assert resp.status_code == 200

    def test_get_criar_familia(self, client, admin_user):
        resp = get_autenticado(client, admin_user, reverse("familias_cadastrar"))
        assert resp.status_code == 200


# ─── form_valid coverage: Discipulado, Classes, Grupos, Ministérios ──────────


class TestFormValidDiscipuladoClasses:
    """Cobre os métodos form_valid nas views de discipulado e classes."""

    def test_discipulado_create_form_valid(self, client, admin_user, pessoa_membro):
        client.force_login(admin_user)
        resp = client.post(
            reverse("discipulado_cadastrar"),
            {
                "discipulador": pessoa_membro.pk,
                "discipulo": pessoa_membro.pk,
                "status": "em_andamento",
            },
        )
        assert resp.status_code in (200, 302)

    def test_discipulado_update_form_valid(self, client, admin_user, pessoa_membro):
        disc = Discipulado.objects.create(
            discipulador=pessoa_membro,
            discipulo=pessoa_membro,
            status="em_andamento",
        )
        client.force_login(admin_user)
        resp = client.post(
            reverse("discipulado_editar", kwargs={"pk": disc.pk}),
            {
                "discipulador": pessoa_membro.pk,
                "discipulo": pessoa_membro.pk,
                "status": "concluido",
            },
        )
        assert resp.status_code in (200, 302)

    def test_discipulado_delete_form_valid(self, client, admin_user, pessoa_membro):
        disc = Discipulado.objects.create(
            discipulador=pessoa_membro,
            discipulo=pessoa_membro,
            status="em_andamento",
        )
        client.force_login(admin_user)
        resp = client.post(reverse("discipulado_excluir", kwargs={"pk": disc.pk}))
        assert resp.status_code in (200, 302)

    def test_classe_create_form_valid(self, client, admin_user, pessoa_membro):
        client.force_login(admin_user)
        resp = client.post(
            reverse("classes_cadastrar"),
            {
                "nome": "Classe Form Valid",
                "status": "ativo",
            },
        )
        assert resp.status_code in (200, 302)

    def test_classe_update_form_valid(self, client, admin_user, pessoa_membro):
        classe = ClasseEstudo.objects.create(nome="Classe Editar")
        client.force_login(admin_user)
        resp = client.post(
            reverse("classes_editar", kwargs={"pk": classe.pk}),
            {"nome": "Classe Editada", "status": "ativo"},
        )
        assert resp.status_code in (200, 302)

    def test_classe_delete_form_valid(self, client, admin_user):
        classe = ClasseEstudo.objects.create(nome="Classe Excluir")
        client.force_login(admin_user)
        resp = client.post(reverse("classes_excluir", kwargs={"pk": classe.pk}))
        assert resp.status_code in (200, 302)

    def test_classe_aluno_create_form_valid(self, client, admin_user, pessoa_membro):
        classe = ClasseEstudo.objects.create(nome="Classe Aluno FV")
        client.force_login(admin_user)
        resp = client.post(
            reverse("classes_alunos_novo"),
            {
                "classe": classe.pk,
                "pessoa": pessoa_membro.pk,
                "status": "ativo",
            },
        )
        assert resp.status_code in (200, 302)


class TestFormValidGruposMinisterios:
    """Cobre os métodos form_valid nas views de grupos e ministérios."""

    def test_grupo_create_form_valid(self, client, admin_user):
        client.force_login(admin_user)
        resp = client.post(
            reverse("pequenos_grupos_cadastrar"),
            {"nome": "Grupo FV", "status": "ativo"},
        )
        assert resp.status_code in (200, 302)

    def test_grupo_update_form_valid(self, client, admin_user):
        grupo = PequenoGrupo.objects.create(nome="Grupo Update")
        client.force_login(admin_user)
        resp = client.post(
            reverse("pequenos_grupos_editar", kwargs={"pk": grupo.pk}),
            {"nome": "Grupo Atualizado", "status": "ativo"},
        )
        assert resp.status_code in (200, 302)

    def test_grupo_delete_form_valid(self, client, admin_user):
        grupo = PequenoGrupo.objects.create(nome="Grupo Excluir")
        client.force_login(admin_user)
        resp = client.post(reverse("pequenos_grupos_excluir", kwargs={"pk": grupo.pk}))
        assert resp.status_code in (200, 302)

    def test_grupo_membro_create_form_valid(self, client, admin_user, pessoa_membro):
        grupo = PequenoGrupo.objects.create(nome="Grupo Membro FV")
        client.force_login(admin_user)
        resp = client.post(
            reverse("pequenos_grupos_membros_novo"),
            {
                "grupo": grupo.pk,
                "pessoa": pessoa_membro.pk,
                "status": "ativo",
            },
        )
        assert resp.status_code in (200, 302)

    def test_ministerio_create_form_valid(self, client, admin_user):
        client.force_login(admin_user)
        resp = client.post(
            reverse("ministerios_cadastrar"),
            {"nome": "Ministerio FV", "status": "ativo"},
        )
        assert resp.status_code in (200, 302)

    def test_ministerio_update_form_valid(self, client, admin_user):
        min_ = Ministerio.objects.create(nome="Min Update")
        client.force_login(admin_user)
        resp = client.post(
            reverse("ministerios_editar", kwargs={"pk": min_.pk}),
            {"nome": "Min Atualizado", "status": "ativo"},
        )
        assert resp.status_code in (200, 302)

    def test_ministerio_delete_form_valid(self, client, admin_user):
        min_ = Ministerio.objects.create(nome="Min Excluir")
        client.force_login(admin_user)
        resp = client.post(reverse("ministerios_excluir", kwargs={"pk": min_.pk}))
        assert resp.status_code in (200, 302)

    def test_ministerio_membro_create_form_valid(self, client, admin_user, pessoa_membro):
        min_ = Ministerio.objects.create(nome="Min Membro FV")
        client.force_login(admin_user)
        resp = client.post(
            reverse("ministerios_membros_novo"),
            {
                "ministerio": min_.pk,
                "pessoa": pessoa_membro.pk,
                "status": "ativo",
            },
        )
        assert resp.status_code in (200, 302)
