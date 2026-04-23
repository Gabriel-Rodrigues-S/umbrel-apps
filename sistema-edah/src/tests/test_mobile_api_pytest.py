import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from church.models import (
    ClasseAluno,
    ClasseEstudo,
    Curso,
    CursoMatricula,
    Discipulado,
    DispositivoFCM,
    Evento,
    EventoInscricao,
    Familia,
    FamiliaMembro,
    Galeria,
    GaleriaFoto,
    Membro,
    Mensagem,
    Ministerio,
    MinisterioMembro,
    NivelAcesso,
    Noticia,
    PedidoOracao,
    PequenoGrupo,
    PequenoGrupoMembro,
    Pessoa,
    StatusEvento,
    StatusMembro,
    TipoEvento,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def membro_ativo(make_user):
    user = make_user(email="membro.ativo@example.com", nome="Membro Ativo", password="SenhaForte123!")
    pessoa = Pessoa.objects.create(
        tipo="membro",
        nome="Membro Ativo",
        email=user.email,
    )
    membro = Membro.objects.create(pessoa=pessoa, status=StatusMembro.ATIVO)
    return user, pessoa, membro


@pytest.fixture
def membro_inativo(make_user):
    user = make_user(email="membro.inativo@example.com", nome="Membro Inativo", password="SenhaForte123!")
    pessoa = Pessoa.objects.create(
        tipo="membro",
        nome="Membro Inativo",
        email=user.email,
    )
    membro = Membro.objects.create(pessoa=pessoa, status=StatusMembro.INATIVO)
    return user, pessoa, membro


@pytest.fixture
def evento_publicado():
    return Evento.objects.create(
        nome="Retiro Jovem",
        descricao="Evento de teste",
        tipo_evento=TipoEvento.RETIRO,
        data_inicio=timezone.now() + timezone.timedelta(days=5),
        status=StatusEvento.ABERTO,
        publicar_app=True,
        capacidade_maxima=2,
    )


def autenticar_com_token(api_client, email, password):
    response = api_client.post(
        "/api/v1/auth/token/",
        {"email": email, "password": password},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    access = response.data["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return response


@pytest.mark.critico
@pytest.mark.integracao
def test_auth_token_retorna_tokens_para_membro_ativo(api_client, membro_ativo):
    user, _, _ = membro_ativo

    response = api_client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SenhaForte123!"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["usuario"]["email"] == user.email


@pytest.mark.critico
@pytest.mark.integracao
def test_auth_token_bloqueia_membro_inativo(api_client, membro_inativo):
    user, _, _ = membro_inativo

    response = api_client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SenhaForte123!"},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.critico
@pytest.mark.integracao
def test_membro_me_get_e_patch(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    response_get = api_client.get("/api/v1/membro/me/")
    assert response_get.status_code == status.HTTP_200_OK
    assert response_get.data["pessoa"]["email"] == user.email

    response_patch = api_client.patch(
        "/api/v1/membro/me/",
        {"telefone": "(92) 99999-9999"},
        format="json",
    )
    assert response_patch.status_code == status.HTTP_200_OK
    assert response_patch.data["pessoa"]["telefone"] == "(92) 99999-9999"


@pytest.mark.critico
@pytest.mark.integracao
def test_eventos_lista_publicados_e_inscricao(api_client, membro_ativo, evento_publicado):
    user, pessoa, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    response_list = api_client.get("/api/v1/eventos/")
    assert response_list.status_code == status.HTTP_200_OK
    assert response_list.data["count"] >= 1

    response_inscrever = api_client.post(f"/api/v1/eventos/{evento_publicado.id}/inscricao/", {}, format="json")
    assert response_inscrever.status_code in {status.HTTP_201_CREATED, status.HTTP_200_OK}

    response_status = api_client.get(f"/api/v1/eventos/{evento_publicado.id}/inscricao/status/")
    assert response_status.status_code == status.HTTP_200_OK
    assert response_status.data["inscrito"] is True


@pytest.mark.critico
@pytest.mark.integracao
def test_push_dispositivo_registra_e_remove(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    response_post = api_client.post(
        "/api/v1/push/dispositivo/",
        {"token": "token-fcm-123", "plataforma": "android"},
        format="json",
    )
    assert response_post.status_code == status.HTTP_200_OK
    assert DispositivoFCM.objects.filter(token="token-fcm-123", usuario=user, ativo=True).exists()

    response_delete = api_client.delete(
        "/api/v1/push/dispositivo/",
        {"token": "token-fcm-123"},
        format="json",
    )
    assert response_delete.status_code == status.HTTP_204_NO_CONTENT
    assert DispositivoFCM.objects.filter(token="token-fcm-123", usuario=user, ativo=False).exists()


@pytest.mark.critico
@pytest.mark.integracao
def test_auth_logout_invalida_refresh(api_client, membro_ativo):
    user, _, _ = membro_ativo
    response_token = api_client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SenhaForte123!"},
        format="json",
    )
    refresh = response_token.data["refresh"]
    access = response_token.data["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    response_logout = api_client.post("/api/v1/auth/logout/", {"refresh": refresh}, format="json")
    assert response_logout.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.critico
@pytest.mark.integracao
def test_oracao_cria_e_lista_somente_do_usuario(api_client, membro_ativo, make_user):
    user, _, _ = membro_ativo

    outro_user = make_user(email="outro@example.com", nome="Outro", password="SenhaForte123!")
    outro_pessoa = Pessoa.objects.create(tipo="membro", nome="Outro", email=outro_user.email)
    Membro.objects.create(pessoa=outro_pessoa, status=StatusMembro.ATIVO)

    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    response_post = api_client.post(
        "/api/v1/oracao/",
        {"pedido": "Orar pela família", "anonimo": False},
        format="json",
    )
    assert response_post.status_code == status.HTTP_201_CREATED

    response_get = api_client.get("/api/v1/oracao/meus/")
    assert response_get.status_code == status.HTTP_200_OK
    assert len(response_get.data) == 1
    assert response_get.data[0]["pedido"] == "Orar pela família"


@pytest.mark.integracao
def test_oracao_patch_e_delete(api_client, membro_ativo):
    user, pessoa, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    pedido = PedidoOracao.objects.create(
        pessoa=pessoa,
        nome=pessoa.nome,
        email=pessoa.email,
        pedido="Pedido inicial",
    )

    response_patch = api_client.patch(
        f"/api/v1/oracao/{pedido.id}/",
        {"pedido": "Pedido atualizado"},
        format="json",
    )
    assert response_patch.status_code == status.HTTP_200_OK
    assert response_patch.data["pedido"] == "Pedido atualizado"

    response_delete = api_client.delete(f"/api/v1/oracao/{pedido.id}/")
    assert response_delete.status_code == status.HTTP_204_NO_CONTENT
    assert not PedidoOracao.objects.filter(pk=pedido.id).exists()


@pytest.mark.integracao
def test_oracao_patch_delete_de_outro_usuario_retorna_404(api_client, membro_ativo, make_user):
    user, _, _ = membro_ativo

    outro_user = make_user(email="outro2@example.com", nome="Outro2", password="SenhaForte123!")
    outra_pessoa = Pessoa.objects.create(tipo="membro", nome="Outro2", email=outro_user.email)
    Membro.objects.create(pessoa=outra_pessoa, status=StatusMembro.ATIVO)
    pedido_outro = PedidoOracao.objects.create(
        pessoa=outra_pessoa, nome=outra_pessoa.nome, email=outra_pessoa.email, pedido="Pedido do outro"
    )

    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    assert api_client.patch(f"/api/v1/oracao/{pedido_outro.id}/", {"pedido": "hack"}, format="json").status_code == status.HTTP_404_NOT_FOUND
    assert api_client.delete(f"/api/v1/oracao/{pedido_outro.id}/").status_code == status.HTTP_404_NOT_FOUND


@pytest.fixture
def admin_com_membro(make_user):
    user = make_user(email="admin.api@example.com", nome="Admin API", password="SenhaForte123!", nivel_acesso=NivelAcesso.ADMIN)
    pessoa = Pessoa.objects.create(tipo="membro", nome="Admin API", email=user.email)
    Membro.objects.create(pessoa=pessoa, status=StatusMembro.ATIVO)
    return user, pessoa


@pytest.mark.integracao
def test_admin_evento_inscricoes_lista_inscritos(api_client, admin_com_membro, evento_publicado, membro_ativo):
    admin_user, _ = admin_com_membro
    _, pessoa_membro, _ = membro_ativo
    EventoInscricao.objects.create(evento=evento_publicado, pessoa=pessoa_membro)

    autenticar_com_token(api_client, admin_user.email, "SenhaForte123!")

    response = api_client.get(f"/api/v1/admin/eventos/{evento_publicado.id}/inscricoes/")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    assert response.data["results"][0]["nome"] == pessoa_membro.nome


@pytest.mark.integracao
def test_admin_evento_inscricoes_membro_comum_retorna_403(api_client, membro_ativo, evento_publicado):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    response = api_client.get(f"/api/v1/admin/eventos/{evento_publicado.id}/inscricoes/")
    assert response.status_code == status.HTTP_403_FORBIDDEN


# ── Edge cases: Auth ──────────────────────────────────────────────────────────


def test_auth_sem_credenciais_retorna_400(api_client):
    resp = api_client.post("/api/v1/auth/token/", {}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_auth_logout_sem_refresh_retorna_400(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.post("/api/v1/auth/logout/", {}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_auth_logout_token_invalido_retorna_400(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.post("/api/v1/auth/logout/", {"refresh": "token-invalido"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ── Edge cases: Eventos ───────────────────────────────────────────────────────


def test_eventos_detail_nao_encontrado(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/eventos/99999/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_inscricao_evento_nao_aberto_retorna_400(api_client, membro_ativo):
    user, _, _ = membro_ativo
    # PLANEJAMENTO está no queryset público mas não aceita inscrições
    evento_planejado = Evento.objects.create(
        nome="Evento Planejado",
        descricao="Planejado",
        tipo_evento=TipoEvento.CULTO,
        data_inicio=timezone.now() + timezone.timedelta(days=10),
        status=StatusEvento.PLANEJAMENTO,
        publicar_app=True,
    )
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.post(f"/api/v1/eventos/{evento_planejado.id}/inscricao/", {}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_inscricao_vagas_esgotadas_retorna_400(api_client, membro_ativo, evento_publicado, make_user):
    user, pessoa, _ = membro_ativo
    # Preenche a capacidade (2 vagas) com outro membro
    outro_pessoa = Pessoa.objects.create(tipo="membro", nome="Outro Vaga", email="outro.vaga@x.com")
    EventoInscricao.objects.create(evento=evento_publicado, pessoa=outro_pessoa)
    EventoInscricao.objects.create(evento=evento_publicado, pessoa=pessoa)

    outro_user = make_user(email="terceiro@x.com", nome="Terceiro", password="SenhaForte123!")
    terceira_pessoa = Pessoa.objects.create(tipo="membro", nome="Terceiro", email="terceiro@x.com")
    Membro.objects.create(pessoa=terceira_pessoa, status=StatusMembro.ATIVO)
    autenticar_com_token(api_client, outro_user.email, "SenhaForte123!")

    resp = api_client.post(f"/api/v1/eventos/{evento_publicado.id}/inscricao/", {}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_inscricao_cancelar_evento(api_client, membro_ativo, evento_publicado):
    user, pessoa, _ = membro_ativo
    EventoInscricao.objects.create(evento=evento_publicado, pessoa=pessoa)
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.delete(f"/api/v1/eventos/{evento_publicado.id}/inscricao/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["deleted"] is True


# ── Edge cases: Notícias ──────────────────────────────────────────────────────


def test_noticias_list_retorna_publicadas(api_client, membro_ativo):
    user, _, _ = membro_ativo
    Noticia.objects.create(
        titulo="Notícia Publicada",
        conteudo="Conteúdo",
        publicar_app=True,
        status="publicado",
        data_publicacao=timezone.now(),
    )
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/noticias/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["count"] >= 1


def test_noticias_detail_nao_encontrada(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/noticias/99999/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ── Edge cases: Grupos e Ministérios ─────────────────────────────────────────


def test_grupos_meus_retorna_lista(api_client, membro_ativo):
    user, pessoa, _ = membro_ativo
    grupo = PequenoGrupo.objects.create(nome="Grupo Edge")
    PequenoGrupoMembro.objects.create(grupo=grupo, pessoa=pessoa)
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/grupos/meus/")
    assert resp.status_code == status.HTTP_200_OK


def test_grupos_detail_nao_encontrado(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/grupos/99999/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_ministerios_meus_retorna_lista(api_client, membro_ativo):
    user, pessoa, _ = membro_ativo
    ministerio = Ministerio.objects.create(nome="Ministério Edge")
    MinisterioMembro.objects.create(ministerio=ministerio, pessoa=pessoa)
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/ministerios/meus/")
    assert resp.status_code == status.HTTP_200_OK


def test_ministerios_detail_nao_encontrado(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/ministerios/99999/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ── Edge cases: Cursos ────────────────────────────────────────────────────────


def test_cursos_list_e_detail(api_client, membro_ativo):
    user, _, _ = membro_ativo
    Curso.objects.create(nome="Curso Edge", descricao="Desc", status="ativo")
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp_list = api_client.get("/api/v1/cursos/")
    assert resp_list.status_code == status.HTTP_200_OK
    assert resp_list.data["count"] >= 1

    curso_id = resp_list.data["results"][0]["id"]
    resp_detail = api_client.get(f"/api/v1/cursos/{curso_id}/")
    assert resp_detail.status_code == status.HTTP_200_OK


def test_cursos_detail_nao_encontrado(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/cursos/99999/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_curso_matricula_e_minhas_matriculas(api_client, membro_ativo):
    user, _, _ = membro_ativo
    curso = Curso.objects.create(nome="Curso Matricula", descricao="D", status="ativo")
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp_post = api_client.post(f"/api/v1/cursos/{curso.id}/matricula/", {}, format="json")
    assert resp_post.status_code == status.HTTP_201_CREATED

    # Segunda chamada retorna 200 (já matriculado)
    resp_dup = api_client.post(f"/api/v1/cursos/{curso.id}/matricula/", {}, format="json")
    assert resp_dup.status_code == status.HTTP_200_OK

    resp_list = api_client.get("/api/v1/cursos/minhas-matriculas/")
    assert resp_list.status_code == status.HTTP_200_OK
    assert len(resp_list.data) >= 1


def test_curso_progresso_nao_encontrado(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/cursos/matriculas/99999/progresso/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_classes_minhas_e_detail(api_client, membro_ativo):
    user, pessoa, _ = membro_ativo
    classe = ClasseEstudo.objects.create(nome="Classe Edge")
    ClasseAluno.objects.create(classe=classe, pessoa=pessoa)
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp_list = api_client.get("/api/v1/classes/minhas/")
    assert resp_list.status_code == status.HTTP_200_OK

    resp_detail = api_client.get(f"/api/v1/classes/{classe.id}/")
    assert resp_detail.status_code == status.HTTP_200_OK


def test_classes_detail_nao_encontrada(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/classes/99999/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ── Edge cases: Galeria ───────────────────────────────────────────────────────


def test_galeria_list_e_fotos(api_client, membro_ativo):
    user, _, _ = membro_ativo
    evento = Evento.objects.create(
        nome="Ev Galeria",
        descricao="D",
        tipo_evento=TipoEvento.CULTO,
        data_inicio=timezone.now(),
        status=StatusEvento.ENCERRADO,
        publicar_app=True,
    )
    galeria = Galeria.objects.create(titulo="Galeria Edge", evento=evento, publicar_app=True)
    GaleriaFoto.objects.create(galeria=galeria, arquivo="foto.jpg", legenda="Legenda")
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp_list = api_client.get("/api/v1/galeria/")
    assert resp_list.status_code == status.HTTP_200_OK

    resp_fotos = api_client.get(f"/api/v1/galeria/{galeria.id}/fotos/")
    assert resp_fotos.status_code == status.HTTP_200_OK
    assert len(resp_fotos.data) == 1


def test_galeria_nao_encontrada(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/galeria/99999/fotos/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ── Edge cases: Família ───────────────────────────────────────────────────────


def test_familia_com_membros(api_client, membro_ativo):
    user, pessoa, _ = membro_ativo
    familia = Familia.objects.create(nome_familia="Família Edge", responsavel=pessoa)
    FamiliaMembro.objects.create(familia=familia, pessoa=pessoa, parentesco="titular")
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/familia/minha/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["familia"]["nome_familia"] == "Família Edge"
    assert len(resp.data["membros"]) == 1


# ── Edge cases: Discipulado ───────────────────────────────────────────────────


def test_discipulado_com_dado(api_client, membro_ativo, make_user):
    user, pessoa, _ = membro_ativo
    discipulador_pessoa = Pessoa.objects.create(tipo="membro", nome="Discipulador", email="disc@x.com")
    Discipulado.objects.create(
        discipulador=discipulador_pessoa,
        discipulo=pessoa,
        status="em_andamento",
    )
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/discipulado/meu/")
    assert resp.status_code == status.HTTP_200_OK
    assert "discipulador" in resp.data


# ── Edge cases: Chat ──────────────────────────────────────────────────────────


def test_chat_mensagens_fluxo_completo(api_client, membro_ativo, make_user):
    user, _, _ = membro_ativo

    outro_user = make_user(email="chat2@x.com", nome="Chat2", password="SenhaForte123!")
    Pessoa.objects.create(tipo="membro", nome="Chat2", email="chat2@x.com")
    Membro.objects.create(
        pessoa=Pessoa.objects.get(email="chat2@x.com"), status=StatusMembro.ATIVO
    )
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    # Enviar mensagem
    resp_post = api_client.post(
        f"/api/v1/chat/mensagens/{outro_user.id}/",
        {"mensagem": "Olá!"},
        format="json",
    )
    assert resp_post.status_code == status.HTTP_201_CREATED

    # Listar mensagens
    resp_get = api_client.get(f"/api/v1/chat/mensagens/{outro_user.id}/")
    assert resp_get.status_code == status.HTTP_200_OK
    assert len(resp_get.data) >= 1

    # Marcar como lidas
    resp_lidas = api_client.patch(f"/api/v1/chat/mensagens/{outro_user.id}/lidas/")
    assert resp_lidas.status_code == status.HTTP_200_OK

    # Ping
    resp_ping = api_client.get("/api/v1/chat/ping/")
    assert resp_ping.status_code == status.HTTP_200_OK
    assert "nao_lidas" in resp_ping.data


def test_chat_usuario_nao_encontrado(api_client, membro_ativo):
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/chat/mensagens/99999/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_chat_mensagem_vazia_retorna_400(api_client, membro_ativo, make_user):
    user, _, _ = membro_ativo
    outro = make_user(email="empty@x.com", nome="Empty", password="SenhaForte123!")
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.post(f"/api/v1/chat/mensagens/{outro.id}/", {"mensagem": ""}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ── Edge cases: Oração ────────────────────────────────────────────────────────


def test_oracao_get_detail_por_id(api_client, membro_ativo):
    user, pessoa, _ = membro_ativo
    pedido = PedidoOracao.objects.create(
        pessoa=pessoa, nome=pessoa.nome, email=pessoa.email, pedido="Pedido GET"
    )
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get(f"/api/v1/oracao/{pedido.id}/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["pedido"] == "Pedido GET"


# ── Edge cases: Chat longa / Delete dispositivo ───────────────────────────────


def test_chat_mensagem_muito_longa_retorna_400(api_client, membro_ativo, make_user):
    user, _, _ = membro_ativo
    outro = make_user(email="longa@x.com", nome="Longa", password="SenhaForte123!")
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.post(
        f"/api/v1/chat/mensagens/{outro.id}/",
        {"mensagem": "x" * 2001},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_push_delete_sem_token_desativa_todos(api_client, membro_ativo):
    """DELETE sem body de token desativa todos os dispositivos do usuário."""
    user, _, _ = membro_ativo
    from church.models import DispositivoFCM
    DispositivoFCM.objects.create(usuario=user, token="tok-todos", plataforma="android", ativo=True)
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.delete("/api/v1/push/dispositivo/", {}, format="json")
    assert resp.status_code == status.HTTP_204_NO_CONTENT
    assert not DispositivoFCM.objects.filter(usuario=user, ativo=True).exists()


# ── Edge cases: Discipulado vazio e ConfiguracaoIgreja com dados ──────────────


def test_discipulado_sem_registro_retorna_vazio(api_client, membro_ativo):
    """Membro sem discipulado retorna {} com 200."""
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/discipulado/meu/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data == {}


def test_configuracoes_get_com_config_existente(api_client, membro_ativo):
    user, _, _ = membro_ativo
    from church.models import ConfiguracaoIgreja, NivelAcesso
    from django.contrib.auth import get_user_model
    User = get_user_model()
    User.objects.filter(email=user.email).update(nivel_acesso=NivelAcesso.ADMIN)
    user.refresh_from_db()

    ConfiguracaoIgreja.objects.create(nome_exibicao="Igreja Config GET")
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get("/api/v1/configuracoes-igreja/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["nome_exibicao"] == "Igreja Config GET"


# ── Edge cases: curso matrícula inativo e grupos detail ──────────────────────


def test_curso_matricula_inativo_retorna_404(api_client, membro_ativo):
    user, _, _ = membro_ativo
    curso = Curso.objects.create(nome="Curso Inativo", descricao="D", status="inativo")
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.post(f"/api/v1/cursos/{curso.id}/matricula/", {}, format="json")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_grupos_detail_retorna_dados(api_client, membro_ativo):
    user, _, _ = membro_ativo
    grupo = PequenoGrupo.objects.create(nome="Grupo Detalhe")
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get(f"/api/v1/grupos/{grupo.id}/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["nome"] == "Grupo Detalhe"


def test_ministerios_detail_retorna_dados(api_client, membro_ativo):
    user, _, _ = membro_ativo
    ministerio = Ministerio.objects.create(nome="Ministerio Detalhe")
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.get(f"/api/v1/ministerios/{ministerio.id}/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["nome"] == "Ministerio Detalhe"


def test_inscricao_evento_inexistente_retorna_404(api_client, membro_ativo):
    """POST/DELETE para evento não publicado retorna 404 em evento_inscricao_view."""
    user, _, _ = membro_ativo
    autenticar_com_token(api_client, user.email, "SenhaForte123!")

    resp = api_client.post("/api/v1/eventos/99999/inscricao/", {}, format="json")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_chat_contatos_inclui_quem_enviou_mensagem_para_usuario(api_client, membro_ativo, make_user):
    """Cobre o branch remetente != usuario.id em chat_contatos_view."""
    user, _, _ = membro_ativo

    outro_user = make_user(email="sender.contato@x.com", nome="Sender", password="SenhaForte123!")
    Pessoa.objects.create(tipo="membro", nome="Sender", email="sender.contato@x.com")
    Membro.objects.create(
        pessoa=Pessoa.objects.get(email="sender.contato@x.com"),
        status=StatusMembro.ATIVO,
    )
    # outro_user envia mensagem PARA user (não o contrário)
    Mensagem.objects.create(remetente=outro_user, destinatario=user, mensagem="Oi!")

    autenticar_com_token(api_client, user.email, "SenhaForte123!")
    resp = api_client.get("/api/v1/chat/contatos/")

    assert resp.status_code == status.HTTP_200_OK
    ids_contatos = [c["id"] for c in resp.data]
    assert outro_user.id in ids_contatos
