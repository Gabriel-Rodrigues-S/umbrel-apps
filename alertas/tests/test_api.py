import json

import httpx
import pytest
from asgi_lifespan import LifespanManager

from alertas import banco, remetentes
from alertas.main import criar_app

pytestmark = pytest.mark.anyio

IP_HOST = "10.21.0.1"
GABRIEL = "g@x"


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def ok(**extra):
    return {"gravidade": "normal", "titulo": "t", "detalhes": "d", **extra}


class PushFalso:
    def __init__(self):
        self.gravidades = []

    def __call__(self, gravidade):
        self.gravidades.append(gravidade)


@pytest.fixture
def dados(tmp_path):
    d = tmp_path / "dados"
    (d / "config").mkdir(parents=True)
    return d


@pytest.fixture
def token_historico(dados):
    return remetentes.criar(dados / "config/remetentes.json", "historico")


@pytest.fixture
def push_falso():
    return PushFalso()


@pytest.fixture
def app(dados, push_falso):
    return criar_app(dados, ip_host=IP_HOST, usuario_permitido=GABRIEL, enviar_push=push_falso)


@pytest.fixture
async def api(app):
    """Cliente vindo de outro contêiner (não é o host)."""
    async with LifespanManager(app) as m:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app, client=("10.21.0.7", 5)),
                                     base_url="http://alertas.teste") as c:
            c.app = app
            yield c


def _gabriel_transport(app):
    return httpx.ASGITransport(app, client=(IP_HOST, 5))


async def listar_como_gabriel(api):
    async with httpx.AsyncClient(transport=_gabriel_transport(api.app),
                                 base_url="http://alertas.teste") as c:
        r = await c.get("/api/alertas", headers={"Tailscale-User-Login": GABRIEL})
        assert r.status_code == 200
        return r.json()


@pytest.fixture
async def gabriel(app):
    async with LifespanManager(app) as m:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app, client=(IP_HOST, 5)),
                                     base_url="http://alertas.teste",
                                     headers={"Tailscale-User-Login": GABRIEL}) as c:
            yield c


# --- testes do brief ---

async def test_origem_vem_do_token_nao_do_corpo(api, token_historico):
    await api.post("/api/alertas", headers=bearer(token_historico),
                   json={"gravidade": "grave", "titulo": "t", "detalhes": "d", "origem": "gateway"})
    assert (await listar_como_gabriel(api))[0]["origem"] == "historico"


async def test_remetente_desconhecido_401_e_um_alerta(api):
    for _ in range(3): assert (await api.post("/api/alertas", headers=bearer("x"), json=ok())).status_code == 401
    assert [a["titulo"] for a in await listar_como_gabriel(api)] == ["Remetente desconhecido"]


async def test_interface_sem_identidade_403(api):
    assert (await api.get("/api/alertas")).status_code == 403


# --- extras ---

ROTAS_PROTEGIDAS = [
    ("GET", "/api/alertas", None),
    ("POST", "/api/alertas/1/lido", None),
    ("GET", "/api/push/chave-publica", None),
    ("POST", "/api/push/inscrever",
     {"endpoint": "https://push.exemplo/a", "keys": {"p256dh": "p", "auth": "a"}}),
    ("GET", "/", None),
    ("GET", "/rota-que-nao-existe", None),
    ("GET", "/docs", None),
    ("GET", "/openapi.json", None),
]


@pytest.mark.parametrize("metodo,rota,corpo", ROTAS_PROTEGIDAS)
async def test_cabecalho_certo_de_ip_errado_403(api, metodo, rota, corpo):
    r = await api.request(metodo, rota, json=corpo, headers={"Tailscale-User-Login": GABRIEL})
    assert r.status_code == 403


@pytest.mark.parametrize("metodo,rota,corpo", ROTAS_PROTEGIDAS)
async def test_ip_do_host_com_outro_usuario_403(gabriel, metodo, rota, corpo):
    r = await gabriel.request(metodo, rota, json=corpo, headers={"Tailscale-User-Login": "outro@x"})
    assert r.status_code == 403


async def test_x_forwarded_for_nao_engana(api):
    r = await api.get("/api/alertas", headers={"Tailscale-User-Login": GABRIEL,
                                               "X-Forwarded-For": IP_HOST, "X-Real-IP": IP_HOST})
    assert r.status_code == 403


@pytest.mark.parametrize("usuario", [None, ""])
async def test_falha_fechada_sem_usuario_permitido(dados, usuario):
    app = criar_app(dados, ip_host=IP_HOST, usuario_permitido=usuario, enviar_push=PushFalso())
    async with LifespanManager(app) as m:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app, client=(IP_HOST, 5)),
                                     base_url="http://a") as c:
            for metodo, rota, corpo in ROTAS_PROTEGIDAS:
                r = await c.request(metodo, rota, json=corpo, headers={"Tailscale-User-Login": ""})
                assert r.status_code == 403
                r = await c.request(metodo, rota, json=corpo, headers={"Tailscale-User-Login": GABRIEL})
                assert r.status_code == 403


async def test_falha_fechada_sem_ip_do_host(dados):
    app = criar_app(dados, ip_host="", usuario_permitido=GABRIEL, enviar_push=PushFalso())
    async with LifespanManager(app) as m:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app, client=("", 5)),
                                     base_url="http://a") as c:
            r = await c.get("/api/alertas", headers={"Tailscale-User-Login": GABRIEL})
            assert r.status_code == 403


async def test_usuario_permitido_vem_do_app_json(dados):
    (dados / "config/app.json").write_text(json.dumps({"usuario_permitido": GABRIEL}))
    app = criar_app(dados, ip_host=IP_HOST, enviar_push=PushFalso())
    async with LifespanManager(app) as m:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app, client=(IP_HOST, 5)),
                                     base_url="http://a") as c:
            assert (await c.get("/api/alertas", headers={"Tailscale-User-Login": GABRIEL})).status_code == 200
            assert (await c.get("/api/alertas", headers={"Tailscale-User-Login": "x@y"})).status_code == 403


async def test_app_json_malformado_nega(dados):
    (dados / "config/app.json").write_text("{ruim")
    app = criar_app(dados, ip_host=IP_HOST, enviar_push=PushFalso())
    async with LifespanManager(app) as m:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app, client=(IP_HOST, 5)),
                                     base_url="http://a") as c:
            assert (await c.get("/api/alertas", headers={"Tailscale-User-Login": GABRIEL})).status_code == 403


async def test_saude_sem_identidade(api):
    r = await api.get("/saude")
    assert r.status_code == 200 and r.json() == {"ok": True}


async def test_post_201_com_id_e_push(api, token_historico, push_falso):
    r = await api.post("/api/alertas", headers=bearer(token_historico), json=ok(gravidade="grave"))
    assert r.status_code == 201 and isinstance(r.json()["id"], int)
    assert push_falso.gravidades == ["grave"]


async def test_info_nao_gera_push(api, token_historico, push_falso):
    r = await api.post("/api/alertas", headers=bearer(token_historico), json=ok(gravidade="info"))
    assert r.status_code == 201
    assert push_falso.gravidades == []


async def test_push_com_erro_nao_derruba_post(dados, token_historico):
    def quebra(gravidade):
        raise RuntimeError("boom")
    app = criar_app(dados, ip_host=IP_HOST, usuario_permitido=GABRIEL, enviar_push=quebra)
    async with LifespanManager(app) as m:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app), base_url="http://a") as c:
            r = await c.post("/api/alertas", headers=bearer(token_historico), json=ok())
            assert r.status_code == 201


@pytest.mark.parametrize("corpo", [
    ok(gravidade="urgente"),
    ok(titulo=""),
    ok(titulo="x" * 121),
    ok(detalhes="x" * 20001),
    {"titulo": "t"},
    ok(titulo=5),
    [],
])
async def test_corpo_invalido_422(api, token_historico, corpo):
    r = await api.post("/api/alertas", headers=bearer(token_historico), json=corpo)
    assert r.status_code == 422
    assert "x" * 50 not in r.text  # não ecoa o corpo


async def test_json_quebrado_422(api, token_historico):
    r = await api.post("/api/alertas", headers={**bearer(token_historico), "Content-Type": "application/json"},
                       content=b"{nao json")
    assert r.status_code == 422


async def test_limites_exatos_aceitos(api, token_historico):
    r = await api.post("/api/alertas", headers=bearer(token_historico),
                       json=ok(titulo="x" * 120, detalhes="y" * 20000))
    assert r.status_code == 201


async def test_token_ausente_401_antes_de_validar_corpo(api):
    r = await api.post("/api/alertas", json={"lixo": 1})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


async def test_alerta_desconhecido_sem_token_no_texto_e_com_ip(api):
    await api.post("/api/alertas", headers=bearer("token-secreto-falso"), json=ok())
    a = (await listar_como_gabriel(api))[0]
    assert a["origem"] == "alertas" and a["gravidade"] == "normal"
    assert "token-secreto-falso" not in a["detalhes"]
    assert "10.21.0.7" in a["detalhes"]


async def test_alerta_desconhecido_gera_push_uma_vez(api, push_falso):
    for _ in range(3):
        await api.post("/api/alertas", headers=bearer("x"), json=ok())
    assert push_falso.gravidades == ["normal"]


async def test_revogar_vale_sem_reiniciar(api, dados, token_historico):
    assert (await api.post("/api/alertas", headers=bearer(token_historico), json=ok())).status_code == 201
    remetentes.revogar(dados / "config/remetentes.json", "historico")
    assert (await api.post("/api/alertas", headers=bearer(token_historico), json=ok())).status_code == 401


async def test_arquivo_de_remetentes_malformado_nega(api, dados, token_historico):
    (dados / "config/remetentes.json").write_text("{ruim")
    assert (await api.post("/api/alertas", headers=bearer(token_historico), json=ok())).status_code == 401


async def test_listar_e_marcar_lido(gabriel, dados, token_historico):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(gabriel._transport.app),
                                 base_url="http://a") as rem:
        r = await rem.post("/api/alertas", headers=bearer(token_historico), json=ok())
    i = r.json()["id"]
    lista = (await gabriel.get("/api/alertas")).json()
    assert lista[0]["id"] == i and lista[0]["lido"] is False
    assert set(lista[0]) == {"id", "origem", "gravidade", "titulo", "detalhes", "criado_em", "lido"}
    assert (await gabriel.post(f"/api/alertas/{i}/lido")).status_code == 204
    assert (await gabriel.get("/api/alertas")).json()[0]["lido"] is True
    assert (await gabriel.post("/api/alertas/9999/lido")).status_code == 404


async def test_chave_publica_e_inscrever(gabriel, dados):
    r = await gabriel.get("/api/push/chave-publica")
    assert r.status_code == 200
    chave = r.json()["chave"]
    assert json.loads((dados / "config/vapid.json").read_text())["publica"] == chave
    s = {"endpoint": "https://push.exemplo/a", "keys": {"p256dh": "p", "auth": "a"}, "extra": 1}
    assert (await gabriel.post("/api/push/inscrever", json=s)).status_code == 201
    assert (await gabriel.post("/api/push/inscrever", json=s)).status_code == 201
    con = banco.abrir(dados / "alertas.db")
    assert banco.inscricoes(con) == [{"endpoint": "https://push.exemplo/a",
                                      "keys": {"p256dh": "p", "auth": "a"}}]
    con.close()


@pytest.mark.parametrize("s", [
    {"endpoint": "http://push.exemplo/a", "keys": {"p256dh": "p", "auth": "a"}},
    {"endpoint": "https://", "keys": {"p256dh": "p", "auth": "a"}},
    {"endpoint": "https://push.exemplo/a", "keys": {"p256dh": "p"}},
    {"endpoint": "https://push.exemplo/a"},
    {"endpoint": "https://push.exemplo/a", "keys": {"p256dh": "", "auth": "a"}},
])
async def test_inscricao_invalida_422(gabriel, s):
    assert (await gabriel.post("/api/push/inscrever", json=s)).status_code == 422


async def test_raiz_placeholder_com_identidade(gabriel):
    r = await gabriel.get("/")
    assert r.status_code == 200
