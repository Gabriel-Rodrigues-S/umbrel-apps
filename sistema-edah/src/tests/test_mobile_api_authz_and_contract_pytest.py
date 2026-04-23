import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from church.models import (
    ClasseAluno,
    ClasseEstudo,
    Curso,
    CursoMatricula,
    CursoNota,
    CursoPresenca,
    Discipulado,
    Evento,
    Galeria,
    GaleriaFoto,
    Mensagem,
    Ministerio,
    MinisterioMembro,
    Membro,
    Noticia,
    PedidoOracao,
    Pessoa,
    PequenoGrupo,
    PequenoGrupoMembro,
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
    user = make_user(email="ativo.authz@example.com", nome="Ativo Authz", password="SenhaForte123!")
    pessoa = Pessoa.objects.create(tipo="membro", nome="Ativo Authz", email=user.email)
    Membro.objects.create(pessoa=pessoa, status=StatusMembro.ATIVO)
    return user, pessoa


@pytest.fixture
def membro_inativo(make_user):
    user = make_user(email="inativo.authz@example.com", nome="Inativo Authz", password="SenhaForte123!")
    pessoa = Pessoa.objects.create(tipo="membro", nome="Inativo Authz", email=user.email)
    Membro.objects.create(pessoa=pessoa, status=StatusMembro.INATIVO)
    return user, pessoa


@pytest.fixture
def ids_base(membro_ativo, make_user):
    user, pessoa = membro_ativo

    evento = Evento.objects.create(
        nome="Evento Authz",
        descricao="Evento",
        tipo_evento=TipoEvento.CULTO,
        data_inicio=timezone.now() + timezone.timedelta(days=1),
        status=StatusEvento.ABERTO,
        publicar_app=True,
    )
    noticia = Noticia.objects.create(
        titulo="Noticia Authz",
        conteudo="Conteudo",
        publicar_app=True,
        status="publicado",
        data_publicacao=timezone.now(),
    )

    grupo = PequenoGrupo.objects.create(nome="Grupo Authz")
    PequenoGrupoMembro.objects.create(grupo=grupo, pessoa=pessoa)

    ministerio = Ministerio.objects.create(nome="Ministerio Authz")
    MinisterioMembro.objects.create(ministerio=ministerio, pessoa=pessoa)

    curso = Curso.objects.create(nome="Curso Authz", status="ativo")
    matricula = CursoMatricula.objects.create(curso=curso, pessoa=pessoa, status="cursando")

    modulo = curso.modulos.create(nome="Modulo 1", ordem=1)
    aula = modulo.aulas.create(titulo="Aula 1", ordem=1)
    CursoPresenca.objects.create(aula=aula, matricula=matricula, data_aula=timezone.localdate(), presente=True)
    CursoNota.objects.create(modulo=modulo, matricula=matricula, nota=8.5, data_avaliacao=timezone.localdate())

    classe = ClasseEstudo.objects.create(nome="Classe Authz")
    ClasseAluno.objects.create(classe=classe, pessoa=pessoa)

    Discipulado.objects.create(
        discipulador=pessoa,
        discipulo=pessoa,
        status="em_andamento",
        data_inicio=timezone.localdate(),
    )

    pedido = PedidoOracao.objects.create(pessoa=pessoa, pedido="Pedido Authz")

    galeria = Galeria.objects.create(titulo="Galeria Authz", publicar_app=True)
    GaleriaFoto.objects.create(galeria=galeria, arquivo="/tmp/foto.jpg", ordem=1)

    outro_user = make_user(email="chat.dest@example.com", nome="Destino Chat", password="SenhaForte123!")
    Mensagem.objects.create(remetente=user, destinatario=outro_user, mensagem="Ola")

    return {
        "evento_id": evento.id,
        "noticia_id": noticia.id,
        "grupo_id": grupo.id,
        "ministerio_id": ministerio.id,
        "curso_id": curso.id,
        "matricula_id": matricula.id,
        "classe_id": classe.id,
        "pedido_id": pedido.id,
        "galeria_id": galeria.id,
        "usuario_chat_id": outro_user.id,
    }


def build_cases(ids):
    return [
        ("get", "/api/v1/membro/me/", None),
        ("patch", "/api/v1/membro/me/", {"telefone": "(92) 99999-0000"}),
        ("get", "/api/v1/eventos/", None),
        ("get", f"/api/v1/eventos/{ids['evento_id']}/", None),
        ("post", f"/api/v1/eventos/{ids['evento_id']}/inscricao/", {}),
        ("delete", f"/api/v1/eventos/{ids['evento_id']}/inscricao/", {}),
        ("get", f"/api/v1/eventos/{ids['evento_id']}/inscricao/status/", None),
        ("get", "/api/v1/noticias/", None),
        ("get", f"/api/v1/noticias/{ids['noticia_id']}/", None),
        ("get", "/api/v1/grupos/meus/", None),
        ("get", f"/api/v1/grupos/{ids['grupo_id']}/", None),
        ("get", "/api/v1/ministerios/meus/", None),
        ("get", f"/api/v1/ministerios/{ids['ministerio_id']}/", None),
        ("get", "/api/v1/cursos/", None),
        ("get", f"/api/v1/cursos/{ids['curso_id']}/", None),
        ("get", "/api/v1/cursos/minhas-matriculas/", None),
        ("post", f"/api/v1/cursos/{ids['curso_id']}/matricula/", {}),
        ("get", f"/api/v1/cursos/matriculas/{ids['matricula_id']}/progresso/", None),
        ("get", "/api/v1/discipulado/meu/", None),
        ("get", "/api/v1/classes/minhas/", None),
        ("get", f"/api/v1/classes/{ids['classe_id']}/", None),
        ("get", "/api/v1/familia/minha/", None),
        ("get", "/api/v1/oracao/meus/", None),
        ("post", "/api/v1/oracao/", {"pedido": "Oracao", "anonimo": False}),
        ("get", f"/api/v1/oracao/{ids['pedido_id']}/", None),
        ("get", "/api/v1/galeria/", None),
        ("get", f"/api/v1/galeria/{ids['galeria_id']}/fotos/", None),
        ("get", "/api/v1/chat/contatos/", None),
        ("get", f"/api/v1/chat/mensagens/{ids['usuario_chat_id']}/", None),
        ("post", f"/api/v1/chat/mensagens/{ids['usuario_chat_id']}/", {"mensagem": "teste"}),
        ("patch", f"/api/v1/chat/mensagens/{ids['usuario_chat_id']}/lidas/", {}),
        ("get", "/api/v1/chat/ping/", None),
        ("post", "/api/v1/push/dispositivo/", {"token": "tok-authz", "plataforma": "android"}),
        ("delete", "/api/v1/push/dispositivo/", {"token": "tok-authz"}),
        ("post", "/api/v1/auth/dispositivo/", {"token": "tok-authz-2", "plataforma": "android"}),
        ("post", "/api/v1/auth/logout/", {"refresh": "qualquer"}),
    ]


@pytest.mark.critico
@pytest.mark.integracao
def test_endpoints_protegidos_negam_anonimo(api_client, ids_base):
    for method, url, payload in build_cases(ids_base):
        response = getattr(api_client, method)(url, payload, format="json")
        assert response.status_code in {401, 403}, f"Falhou em {method.upper()} {url}: {response.status_code}"


@pytest.mark.critico
@pytest.mark.integracao
def test_endpoints_protegidos_negam_membro_inativo(api_client, membro_inativo, ids_base):
    user, _ = membro_inativo
    api_client.force_authenticate(user=user)

    for method, url, payload in build_cases(ids_base):
        response = getattr(api_client, method)(url, payload, format="json")
        assert response.status_code == 403, f"Falhou em {method.upper()} {url}: {response.status_code}"


@pytest.mark.critico
@pytest.mark.integracao
def test_contrato_chat_progresso_familia(api_client, membro_ativo, ids_base):
    user, _ = membro_ativo
    token_response = api_client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SenhaForte123!"},
        format="json",
    )
    access = token_response.data["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    response_contatos = api_client.get("/api/v1/chat/contatos/")
    assert response_contatos.status_code == 200
    assert isinstance(response_contatos.data, list)
    if response_contatos.data:
        contato = response_contatos.data[0]
        assert "id" in contato and "nome" in contato and "nao_lidas" in contato

    response_progresso = api_client.get(f"/api/v1/cursos/matriculas/{ids_base['matricula_id']}/progresso/")
    assert response_progresso.status_code == 200
    assert "matricula_id" in response_progresso.data
    assert "presencas" in response_progresso.data
    assert "notas" in response_progresso.data

    response_familia = api_client.get("/api/v1/familia/minha/")
    assert response_familia.status_code == 200
    assert "familia" in response_familia.data
    assert "membros" in response_familia.data


@pytest.mark.integracao
def test_todos_endpoints_retornam_2xx_para_membro_ativo(api_client, membro_ativo, ids_base):
    """
    Garante que todos os endpoints retornam 2xx para um membro ativo autenticado.
    Cobre os caminhos de sucesso de cada view.
    """
    user, _ = membro_ativo
    token_response = api_client.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": "SenhaForte123!"},
        format="json",
    )
    access = token_response.data["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    # Logout requer refresh token válido — testado separadamente
    casos = [(m, u, p) for m, u, p in build_cases(ids_base) if u != "/api/v1/auth/logout/"]

    for method, url, payload in casos:
        response = getattr(api_client, method)(url, payload, format="json")
        assert response.status_code in range(200, 300), (
            f"Esperado 2xx em {method.upper()} {url}, obtido {response.status_code}: {response.data}"
        )
