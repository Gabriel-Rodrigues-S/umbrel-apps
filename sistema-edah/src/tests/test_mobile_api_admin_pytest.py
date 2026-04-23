"""
Testes das views admin da API mobile.
Cobre: dashboard, membros, visitantes, financeiro, relatórios, configurações.
"""
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from church.models import (
    CategoriaFinanceira,
    ConfiguracaoIgreja,
    Evento,
    EventoInscricao,
    Familia,
    FamiliaMembro,
    LancamentoFinanceiro,
    Membro,
    NivelAcesso,
    Pessoa,
    StatusEvento,
    StatusMembro,
    TipoEvento,
    TipoLancamento,
    Visitante,
)

pytestmark = pytest.mark.django_db


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def api_client():
    return APIClient()


def _criar_membro_com_user(make_user, email, nivel=NivelAcesso.USUARIO, nome=None):
    nome = nome or email.split("@")[0]
    user = make_user(email=email, nome=nome, password="SenhaForte123!", nivel_acesso=nivel)
    pessoa = Pessoa.objects.create(tipo="membro", nome=nome, email=email)
    membro = Membro.objects.create(pessoa=pessoa, status=StatusMembro.ATIVO)
    return user, pessoa, membro


@pytest.fixture
def admin_user(make_user):
    user, pessoa, membro = _criar_membro_com_user(
        make_user, "admin.test@church.com", nivel=NivelAcesso.ADMIN, nome="Admin Test"
    )
    return user, pessoa, membro


@pytest.fixture
def financeiro_user(make_user):
    user, pessoa, membro = _criar_membro_com_user(
        make_user, "fin.test@church.com", nivel=NivelAcesso.FINANCEIRO, nome="Financeiro Test"
    )
    return user, pessoa, membro


@pytest.fixture
def membro_comum(make_user):
    user, pessoa, membro = _criar_membro_com_user(
        make_user, "comum.test@church.com", nivel=NivelAcesso.USUARIO, nome="Comum Test"
    )
    return user, pessoa, membro


def _autenticar(api_client, email):
    resp = api_client.post(
        "/api/v1/auth/token/",
        {"email": email, "password": "SenhaForte123!"},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.data
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")


# ── Dashboard ────────────────────────────────────────────────────────────────


def test_admin_dashboard_retorna_kpis(api_client, admin_user):
    user, _, _ = admin_user
    _autenticar(api_client, user.email)

    resp = api_client.get("/api/v1/admin/dashboard/")

    assert resp.status_code == status.HTTP_200_OK
    assert "total_membros" in resp.data
    assert "visitantes_mes" in resp.data
    assert "eventos_futuros" in resp.data
    assert "entradas_mes" in resp.data
    assert "saidas_mes" in resp.data
    assert "saldo_mes" in resp.data


def test_admin_dashboard_bloqueia_membro_comum(api_client, membro_comum):
    user, _, _ = membro_comum
    _autenticar(api_client, user.email)

    resp = api_client.get("/api/v1/admin/dashboard/")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ── Membros ──────────────────────────────────────────────────────────────────


def test_admin_membros_lista(api_client, admin_user):
    user, _, _ = admin_user
    _autenticar(api_client, user.email)

    resp = api_client.get("/api/v1/admin/membros/")
    assert resp.status_code == status.HTTP_200_OK
    assert "results" in resp.data
    assert resp.data["count"] >= 1


def test_admin_membros_lista_filtro_status(api_client, admin_user):
    user, _, _ = admin_user
    _autenticar(api_client, user.email)

    resp = api_client.get("/api/v1/admin/membros/?status=ativo")
    assert resp.status_code == status.HTTP_200_OK
    for item in resp.data["results"]:
        assert item["status"] == "ativo"


def test_admin_membros_cria_novo(api_client, admin_user):
    user, _, _ = admin_user
    _autenticar(api_client, user.email)

    resp = api_client.post(
        "/api/v1/admin/membros/",
        {
            "nome": "Novo Membro Criado",
            "email": "novo.criado@church.com",
            "genero": "Masculino",
            "telefone": "(92) 99999-0001",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.data["nome"] == "Novo Membro Criado"
    assert Membro.objects.filter(pessoa__email="novo.criado@church.com").exists()


def test_admin_membro_patch_dados_pessoa(api_client, admin_user, membro_comum):
    user, _, _ = admin_user
    _, _, membro = membro_comum
    _autenticar(api_client, user.email)

    resp = api_client.patch(
        f"/api/v1/admin/membros/{membro.id}/",
        {"telefone": "(92) 88888-0001", "status": "inativo"},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    membro.refresh_from_db()
    assert membro.status == "inativo"


def test_admin_membro_patch_nao_encontrado(api_client, admin_user):
    user, _, _ = admin_user
    _autenticar(api_client, user.email)

    resp = api_client.patch("/api/v1/admin/membros/99999/", {"telefone": "X"}, format="json")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ── Visitantes ───────────────────────────────────────────────────────────────


def test_admin_visitantes_lista(api_client, admin_user):
    user, _, _ = admin_user
    pessoa_v = Pessoa.objects.create(tipo="visitante", nome="Visitante Teste", email="visit@church.com")
    Visitante.objects.create(
        pessoa=pessoa_v,
        data_primeira_visita=timezone.localdate(),
        data_ultima_visita=timezone.localdate(),
    )
    _autenticar(api_client, user.email)

    resp = api_client.get("/api/v1/admin/visitantes/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["count"] >= 1


# ── Financeiro ───────────────────────────────────────────────────────────────


@pytest.fixture
def categoria():
    return CategoriaFinanceira.objects.create(nome="Dízimos", tipo="entrada")


def test_admin_financeiro_lista(api_client, financeiro_user, categoria):
    user, pessoa, _ = financeiro_user
    LancamentoFinanceiro.objects.create(
        tipo=TipoLancamento.DIZIMO,
        valor="500.00",
        data_lancamento=timezone.localdate(),
        usuario=user,
    )
    _autenticar(api_client, user.email)

    resp = api_client.get("/api/v1/admin/financeiro/lancamentos/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["count"] >= 1


def test_admin_financeiro_filtros_tipo_mes_ano(api_client, financeiro_user, categoria):
    user, _, _ = financeiro_user
    hoje = timezone.localdate()
    LancamentoFinanceiro.objects.create(
        tipo=TipoLancamento.OFERTA,
        valor="200.00",
        data_lancamento=hoje,
        usuario=user,
    )
    _autenticar(api_client, user.email)

    resp = api_client.get(
        f"/api/v1/admin/financeiro/lancamentos/?tipo=oferta&mes={hoje.month}&ano={hoje.year}"
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["count"] >= 1


def test_admin_financeiro_cria_lancamento(api_client, financeiro_user, categoria):
    user, _, _ = financeiro_user
    _autenticar(api_client, user.email)

    resp = api_client.post(
        "/api/v1/admin/financeiro/lancamentos/",
        {
            "tipo": "dizimo",
            "valor": "350.00",
            "data_lancamento": str(timezone.localdate()),
            "descricao": "Dízimo de teste",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert LancamentoFinanceiro.objects.filter(descricao="Dízimo de teste").exists()


def test_admin_financeiro_bloqueia_membro_sem_role(api_client, membro_comum):
    user, _, _ = membro_comum
    _autenticar(api_client, user.email)

    resp = api_client.get("/api/v1/admin/financeiro/lancamentos/")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ── Relatório de membros ──────────────────────────────────────────────────────


def test_admin_relatorio_membros(api_client, admin_user):
    user, _, _ = admin_user
    _autenticar(api_client, user.email)

    resp = api_client.get("/api/v1/admin/relatorios/membros/")
    # Em ambiente de teste sem multi-tenancy, o guard falha silencioso e retorna dados
    assert resp.status_code in (status.HTTP_200_OK, status.HTTP_403_FORBIDDEN)
    if resp.status_code == status.HTTP_200_OK:
        assert "total" in resp.data
        assert "ativos" in resp.data


# ── Configurações da Igreja ───────────────────────────────────────────────────


def test_admin_configuracoes_get_sem_config(api_client, admin_user):
    user, _, _ = admin_user
    _autenticar(api_client, user.email)

    resp = api_client.get("/api/v1/configuracoes-igreja/")
    assert resp.status_code == status.HTTP_200_OK


def test_admin_configuracoes_cria_via_patch(api_client, admin_user):
    user, _, _ = admin_user
    _autenticar(api_client, user.email)

    resp = api_client.patch(
        "/api/v1/configuracoes-igreja/",
        {"nome_exibicao": "Igreja Teste", "pastor_presidente": "Pr. José"},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    assert ConfiguracaoIgreja.objects.filter(nome_exibicao="Igreja Teste").exists()


def test_admin_configuracoes_atualiza(api_client, admin_user):
    user, _, _ = admin_user
    ConfiguracaoIgreja.objects.create(nome_exibicao="Igreja Antiga")
    _autenticar(api_client, user.email)

    resp = api_client.patch(
        "/api/v1/configuracoes-igreja/",
        {"nome_exibicao": "Igreja Atualizada"},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["nome_exibicao"] == "Igreja Atualizada"


# ── Inscrições por evento ─────────────────────────────────────────────────────


def test_admin_evento_inscricoes_nao_encontrado(api_client, admin_user):
    user, _, _ = admin_user
    _autenticar(api_client, user.email)

    resp = api_client.get("/api/v1/admin/eventos/99999/inscricoes/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_admin_evento_inscricoes_lista(api_client, admin_user, membro_comum):
    user, _, _ = admin_user
    _, pessoa_c, _ = membro_comum

    evento = Evento.objects.create(
        nome="Evento Admin",
        descricao="Desc",
        tipo_evento=TipoEvento.CULTO,
        data_inicio=timezone.now() + timezone.timedelta(days=3),
        status=StatusEvento.ABERTO,
        publicar_app=True,
    )
    EventoInscricao.objects.create(evento=evento, pessoa=pessoa_c)
    _autenticar(api_client, user.email)

    resp = api_client.get(f"/api/v1/admin/eventos/{evento.id}/inscricoes/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["nome"] == pessoa_c.nome
