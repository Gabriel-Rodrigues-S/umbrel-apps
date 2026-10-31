import json
import os
import time
from datetime import datetime, timedelta, timezone

import anyio
import httpx
import pytest
from asgi_lifespan import LifespanManager

from vault_gateway import auditoria, ferramentas, tokens
from vault_gateway.rajada import Rajada
from vault_gateway.servidor import criar_app, proximas_8h, resumo_diario

pytestmark = pytest.mark.anyio

ACEITA = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def rpc(metodo, params=None, id_=1):
    m = {"jsonrpc": "2.0", "id": id_, "method": metodo}
    if params is not None:
        m["params"] = params
    return m


def linhas(log):
    if not log.exists():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]


def ultima_linha(log):
    return linhas(log)[-1]


class AvisosFalsos:
    def __init__(self, espera=0.0):
        self.enviados = []
        self.reenvios = 0
        self.espera = espera

    def guardar(self, gravidade, titulo, detalhes):
        self.enviados.append({"gravidade": gravidade, "titulo": titulo, "detalhes": detalhes})
        return True

    def reenviar_fila(self):
        # a rede lenta fica só no drenador
        if self.espera:
            time.sleep(self.espera)
        self.reenvios += 1
        return 0


@pytest.fixture
def dados(tmp_path):
    d = tmp_path / "dados"
    d.mkdir()
    return d


@pytest.fixture
def token(dados):
    return tokens.criar(dados / "config/tokens.json", "claude")


@pytest.fixture
def avisos_falsos():
    return AvisosFalsos()


@pytest.fixture
def app(vault, dados, token, avisos_falsos):
    (dados / "config").mkdir(exist_ok=True)
    (dados / "config/inbox.json").write_text('{"clientes": ["claude"]}', encoding="utf-8")
    return criar_app(vault, dados, avisos=avisos_falsos)


@pytest.fixture
async def cliente(app):
    async with LifespanManager(app) as m:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app),
                                     base_url="http://gateway.teste", headers=ACEITA) as c:
            yield c


@pytest.fixture
async def cliente_autenticado(app, token):
    async with LifespanManager(app) as m:
        cab = {**ACEITA, "Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app),
                                     base_url="http://gateway.teste", headers=cab) as c:
            yield c


async def esperar(app):
    """Espera o envio de avisos em segundo plano terminar."""
    await anyio.to_thread.run_sync(app.state.esperar_avisos)


async def listar_ferramentas(c):
    r = await c.post("/mcp", json=rpc("tools/list"))
    assert r.status_code == 200
    return r.json()["result"]["tools"]


async def chamar(c, nome, args):
    r = await c.post("/mcp", json=rpc("tools/call", {"name": nome, "arguments": args}))
    assert r.status_code == 200
    return r.json()["result"]


def texto(resultado):
    return resultado["content"][0]["text"]


# --- testes do brief ---

async def test_sem_token_401_e_registrado(cliente, dados):
    r = await cliente.post("/mcp", json=rpc("tools/list"))
    assert r.status_code == 401
    assert r.json() == {"erro": "não autorizado"}
    assert r.headers["www-authenticate"] == "Bearer"
    reg = ultima_linha(dados / "logs/acesso.jsonl")
    assert reg["motivo"] == "token_ausente" and reg["resultado"] == "negada"


async def test_token_valido_lista_5_ferramentas(cliente_autenticado):
    nomes = {t["name"] for t in await listar_ferramentas(cliente_autenticado)}
    assert nomes == {"listar", "ler", "buscar", "recentes", "criar_nota"}


async def test_token_valido_fora_do_vault_gera_aviso_grave(cliente_autenticado, avisos_falsos, app, dados):
    res = await chamar(cliente_autenticado, "ler", {"caminho": "../../etc/passwd"})
    assert res["isError"] is True and texto(res) == "Acesso negado."
    await esperar(app)
    g = avisos_falsos.enviados[-1]
    assert g["gravidade"] == "grave" and "claude" in g["titulo"]
    assert g["titulo"] == "Tentativa negada: cliente claude"
    assert g["detalhes"] == "ferramenta: ler\nalvo: ../../etc/passwd\nmotivo: fora_do_vault"
    reg = ultima_linha(dados / "logs/acesso.jsonl")
    assert (reg["cliente"], reg["resultado"], reg["motivo"]) == ("claude", "negada", "fora_do_vault")


async def test_21_tokens_invalidos_um_aviso_normal(cliente, avisos_falsos, app):
    for _ in range(21):
        await cliente.post("/mcp", json=rpc("tools/list"), headers={"Authorization": "Bearer x"})
    await esperar(app)
    assert [a["gravidade"] for a in avisos_falsos.enviados] == ["normal"]
    a = avisos_falsos.enviados[0]
    assert a["titulo"] == "Rajada de tokens inválidos" and "21" in a["detalhes"]


async def test_saude_nao_revela_nada(cliente):
    assert (await cliente.get("/saude")).json() == {"ok": True}


# --- testes adicionais ---

async def test_raiz_mostra_so_status(cliente):
    r = await cliente.get("/")
    assert r.status_code == 200 and "Gateway do vault — ativo" in r.text
    assert "claude" not in r.text


async def test_token_invalido_registrado_sem_o_token(cliente, dados):
    r = await cliente.post("/mcp", json=rpc("tools/list"),
                           headers={"Authorization": "Bearer segredo-errado-123"})
    assert r.status_code == 401
    reg = ultima_linha(dados / "logs/acesso.jsonl")
    assert reg["motivo"] == "token_invalido" and reg["cliente"] == "desconhecido"
    assert "segredo-errado-123" not in (dados / "logs/acesso.jsonl").read_text()


async def test_barra_final_funciona_sem_redirecionar(cliente_autenticado):
    r = await cliente_autenticado.post("/mcp/", json=rpc("tools/list"))
    assert r.status_code == 200
    assert len(r.json()["result"]["tools"]) == 5


async def test_barra_final_sem_token_401(cliente):
    r = await cliente.post("/mcp/", json=rpc("tools/list"))
    assert r.status_code == 401


@pytest.mark.parametrize("modelo,motivo", [
    ("Basic {t}", "token_invalido"),
    ("Bearer", "token_invalido"),
    ("Bearer ", "token_invalido"),
    ("{t}", "token_invalido"),
    ("Bearer {t} extra", "token_invalido"),
    ("Bearer{t}", "token_invalido"),
    ("", "token_ausente"),
])
async def test_formatos_ruins_de_cabecalho(cliente, dados, token, modelo, motivo):
    r = await cliente.post("/mcp", json=rpc("tools/list"),
                           headers={"Authorization": modelo.format(t=token)})
    assert r.status_code == 401
    assert ultima_linha(dados / "logs/acesso.jsonl")["motivo"] == motivo


async def test_esquema_bearer_ignora_caixa(cliente, token):
    r = await cliente.post("/mcp", json=rpc("tools/list"),
                           headers={"Authorization": f"bearer {token}"})
    assert r.status_code == 200


async def test_token_revogado_deixa_de_valer(cliente_autenticado, dados):
    assert (await cliente_autenticado.post("/mcp", json=rpc("tools/list"))).status_code == 200
    tokens.revogar(dados / "config/tokens.json", "claude")
    assert (await cliente_autenticado.post("/mcp", json=rpc("tools/list"))).status_code == 401


async def test_chamada_permitida_registra_cliente(cliente_autenticado, dados, avisos_falsos, app):
    res = await chamar(cliente_autenticado, "ler", {"caminho": "Referências/Nota com acento.md"})
    assert res["isError"] is False and texto(res) == "# Nota\ncorpo\n"
    reg = ultima_linha(dados / "logs/acesso.jsonl")
    assert reg == {**reg, "cliente": "claude", "ferramenta": "ler", "resultado": "permitida",
                   "alvo": "Referências/Nota com acento.md", "motivo": None}
    await esperar(app)
    assert avisos_falsos.enviados == []


async def test_nao_encontrado_mensagem_neutra(cliente_autenticado, dados, avisos_falsos, app):
    res = await chamar(cliente_autenticado, "ler", {"caminho": "nao-existe.md"})
    assert res["isError"] is True and texto(res) == "Não encontrado."
    assert ultima_linha(dados / "logs/acesso.jsonl")["resultado"] == "permitida"
    await esperar(app)
    assert avisos_falsos.enviados == []


async def test_excluido_mensagem_neutra(cliente_autenticado, dados, avisos_falsos, app):
    res = await chamar(cliente_autenticado, "ler", {"caminho": ".obsidian/x.json"})
    assert texto(res) == "Acesso negado."
    assert ultima_linha(dados / "logs/acesso.jsonl")["motivo"] == "excluido"
    # mesma resposta para caminho excluído inexistente
    res2 = await chamar(cliente_autenticado, "ler", {"caminho": ".obsidian/nada.json"})
    assert texto(res2) == "Acesso negado."
    await esperar(app)
    assert [a["gravidade"] for a in avisos_falsos.enviados] == ["grave", "grave"]


async def test_listar_buscar_recentes(cliente_autenticado):
    lista = json.loads(texto(await chamar(cliente_autenticado, "listar", {})))
    assert {"nome": "Referências", "tipo": "pasta"} in lista
    achados = json.loads(texto(await chamar(cliente_autenticado, "buscar", {"texto": "corpo"})))
    assert "Referências/Nota com acento.md" in {a["caminho"] for a in achados}
    rec = json.loads(texto(await chamar(cliente_autenticado, "recentes", {"n": 0})))
    assert len(rec) == 1  # n limitado a 1..100


async def test_buscar_limite_limitado(cliente_autenticado, vault):
    for i in range(60):
        (vault / f"n{i:02}.md").write_text("agulha")
    achados = json.loads(texto(await chamar(cliente_autenticado, "buscar",
                                            {"texto": "agulha", "limite": 1000})))
    assert len(achados) == 50


async def test_nome_com_bytes_invalidos_nao_quebra(cliente_autenticado, vault):
    os.close(os.open(os.fsencode(vault) + b"/ru\xffido.md", os.O_CREAT | os.O_WRONLY))
    res = await chamar(cliente_autenticado, "listar", {})
    assert res["isError"] is False
    nomes = [i["nome"] for i in json.loads(texto(res))]
    assert any(n.startswith("ru") and n.endswith("ido.md") for n in nomes)
    res = await chamar(cliente_autenticado, "recentes", {"n": 100})
    assert res["isError"] is False


async def test_ferramenta_desconhecida_negada(cliente_autenticado, dados, avisos_falsos, app):
    res = await chamar(cliente_autenticado, "apagar", {"caminho": "x"})
    assert res["isError"] is True and "apagar" not in texto(res)
    reg = ultima_linha(dados / "logs/acesso.jsonl")
    assert (reg["resultado"], reg["motivo"], reg["ferramenta"]) == ("negada", "ferramenta_desconhecida", "apagar")
    await esperar(app)
    assert avisos_falsos.enviados[-1]["gravidade"] == "grave"
    assert "motivo: ferramenta_desconhecida" in avisos_falsos.enviados[-1]["detalhes"]


async def test_erro_inesperado_nao_vaza(cliente_autenticado, monkeypatch):
    def explode(raiz, caminho):
        raise RuntimeError("/caminho/absoluto/segredo")
    monkeypatch.setattr(ferramentas, "ler", explode)
    res = await chamar(cliente_autenticado, "ler", {"caminho": "a.md"})
    assert res["isError"] is True and texto(res) == "Erro interno."


async def test_argumento_invalido_nao_vaza(cliente_autenticado):
    res = await chamar(cliente_autenticado, "ler", {})
    assert res["isError"] is True and texto(res) == "Argumentos inválidos."


async def test_falha_no_log_nao_derruba(cliente_autenticado, monkeypatch):
    def falha(*a, **k):
        raise OSError("disco cheio")
    monkeypatch.setattr(auditoria, "registrar", falha)
    res = await chamar(cliente_autenticado, "ler", {"caminho": "Referências/Nota com acento.md"})
    assert res["isError"] is False
    r = await cliente_autenticado.post("/mcp", json=rpc("tools/list"),
                                       headers={"Authorization": "Bearer errado"})
    assert r.status_code == 401


async def test_alvo_longo_truncado(cliente_autenticado, avisos_falsos, app, dados):
    await chamar(cliente_autenticado, "ler", {"caminho": "../" + "x" * 5000})
    await esperar(app)
    assert len(avisos_falsos.enviados[-1]["detalhes"]) < 400
    assert len(ultima_linha(dados / "logs/acesso.jsonl")["alvo"]) <= 300


async def test_aviso_lento_nao_trava_requisicao(vault, dados, token):
    lento = AvisosFalsos(espera=2.0)
    app = criar_app(vault, dados, avisos=lento)
    async with LifespanManager(app) as m:
        cab = {**ACEITA, "Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app),
                                     base_url="http://gateway.teste", headers=cab) as c:
            inicio = time.monotonic()
            res = await chamar(c, "ler", {"caminho": "../fora.md"})
            assert time.monotonic() - inicio < 1.0
            assert texto(res) == "Acesso negado."
            # fila primeiro: já gravado antes de qualquer rede
            assert lento.enviados[-1]["gravidade"] == "grave"
            await esperar(app)


async def test_lifespan_reenvia_fila_ao_iniciar(app, avisos_falsos):
    async with LifespanManager(app):
        for _ in range(50):
            if avisos_falsos.reenvios:
                break
            await anyio.sleep(0.02)
    assert avisos_falsos.reenvios >= 1


# --- resumo diário ---

def test_proximas_8h():
    tz = timezone(timedelta(hours=-4))
    assert proximas_8h(datetime(2026, 10, 26, 7, 59, tzinfo=tz)) == datetime(2026, 10, 26, 8, 0, tzinfo=tz)
    assert proximas_8h(datetime(2026, 10, 26, 8, 0, tzinfo=tz)) == datetime(2026, 10, 27, 8, 0, tzinfo=tz)
    assert proximas_8h(datetime(2026, 10, 26, 23, 30, tzinfo=tz)) == datetime(2026, 10, 27, 8, 0, tzinfo=tz)
    assert proximas_8h(datetime(2026, 12, 31, 9, 0, tzinfo=tz)) == datetime(2027, 1, 1, 8, 0, tzinfo=tz)


def test_resumo_diario_envia_info_e_zera():
    r = Rajada()
    for t in range(5):
        r.contar(t)
    av = AvisosFalsos()
    resumo_diario(r, av.guardar)
    assert av.enviados == [{"gravidade": "info", "titulo": "Resumo diário",
                            "detalhes": "Tentativas com token ausente ou inválido nas últimas 24 h: 5"}]
    assert r.total_do_dia() == 0


# --- configuração padrão de avisos ---

def test_sem_avisos_json_guarda_na_fila(vault, dados, token, monkeypatch):
    monkeypatch.setenv("REMETENTE", "gateway")
    app = criar_app(vault, dados)
    app.state.avisos.enviar("grave", "t", "d")
    assert len(list((dados / "fila-avisos" / "gateway").glob("*.json"))) == 1


async def test_rajada_de_avisos_drena_uma_vez_por_vez(vault, dados, token):
    """Vários avisos com o alertas lento: tudo gravado; drenagens não se empilham."""
    lento = AvisosFalsos(espera=0.3)
    app = criar_app(vault, dados, avisos=lento)
    async with LifespanManager(app) as m:
        cab = {**ACEITA, "Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app),
                                     base_url="http://gateway.teste", headers=cab) as c:
            for _ in range(5):
                await chamar(c, "ler", {"caminho": "../fora.md"})
            await esperar(app)
    assert [a["gravidade"] for a in lento.enviados] == ["grave"] * 5
    assert lento.reenvios <= 4  # 1 do início + no máximo 1 ativa e 1 na espera por rajada


async def test_gateway_real_grava_na_fila_antes_da_rede(vault, dados, token):
    """Com Avisos real e alertas fora do ar, o grave fica no disco (sobrevive a SIGKILL)."""
    from vault_gateway.avisos import Avisos

    def fora(req):
        raise httpx.ConnectError("fora", request=req)

    av = Avisos("http://alertas.teste", "t", dados / "fila-avisos" / "gateway",
                cliente=httpx.Client(transport=httpx.MockTransport(fora)))
    app = criar_app(vault, dados, avisos=av)
    async with LifespanManager(app) as m:
        cab = {**ACEITA, "Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app),
                                     base_url="http://gateway.teste", headers=cab) as c:
            await chamar(c, "ler", {"caminho": "../fora.md"})
            arquivos = list((dados / "fila-avisos" / "gateway").glob("*.json"))
            assert len(arquivos) == 1  # gravado já no caminho da requisição
            assert json.loads(arquivos[0].read_text())["gravidade"] == "grave"
            await esperar(app)


async def test_initialize_e_notificacao(cliente_autenticado):
    r = await cliente_autenticado.post("/mcp", json=rpc("initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "teste", "version": "0"}}))
    assert r.status_code == 200
    assert r.json()["result"]["serverInfo"]["name"] == "vault-gateway"
    r = await cliente_autenticado.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202


# --- criar_nota (Inbox) ---

SUCESSO = "Nota guardada: Inbox/T.md. Ela entra no vault quando o PC buscar."
MENSAGENS = {
    "fora_da_inbox": "Acesso negado: a nota só pode ser criada na Inbox, sem pastas no nome.",
    "nome_invalido": "Nome inválido: use só o nome do arquivo .md (letras, números, espaço, - _ . ( )).",
    "ja_existe": "Já existe uma nota com esse nome na Inbox.",
    "conteudo_invalido": "Conteúdo inválido: texto não vazio, até 100 KB.",
    "sem_permissao": "Acesso negado.",
}


async def test_criar_nota_grava_registra_e_avisa_normal(cliente_autenticado, avisos_falsos, app, dados):
    res = await chamar(cliente_autenticado, "criar_nota", {"nome": "T.md", "conteudo": "corpo"})
    assert not res.get("isError") and texto(res) == SUCESSO
    assert (dados / "inbox" / "T.md").read_text() == "corpo"
    await esperar(app)
    linha = ultima_linha(dados / "logs/acesso.jsonl")
    assert (linha["ferramenta"], linha["alvo"], linha["resultado"], linha["bytes"]) == (
        "criar_nota", "T.md", "permitida", 5)
    assert "corpo" not in json.dumps(linha)
    a = avisos_falsos.enviados[-1]
    assert a["gravidade"] == "normal" and a["titulo"] == "Nota nova na Inbox"
    assert a["detalhes"] == "nome: T.md\ntamanho: 5 bytes\ncliente: claude"
    assert "corpo" not in json.dumps(avisos_falsos.enviados)


async def checar_negada(c, app, avisos, dados, args, motivo, mensagem):
    res = await chamar(c, "criar_nota", args)
    assert res["isError"] is True and texto(res) == mensagem
    await esperar(app)
    linha = ultima_linha(dados / "logs/acesso.jsonl")
    assert linha["resultado"] == "negada" and linha["motivo"] == motivo
    a = avisos.enviados[-1]
    assert a["gravidade"] == "grave" and a["titulo"] == "Tentativa negada: cliente claude"
    assert f"motivo: {motivo}" in a["detalhes"]


@pytest.mark.parametrize("nome,motivo", [("../x.md", "fora_da_inbox"), ("x.txt", "nome_invalido")])
async def test_criar_nota_negada_gera_grave(cliente_autenticado, avisos_falsos, app, dados, nome, motivo):
    await checar_negada(cliente_autenticado, app, avisos_falsos, dados,
                        {"nome": nome, "conteudo": "x"}, motivo, MENSAGENS[motivo])


async def test_alerta_nao_aceita_quebra_de_linha_no_nome(cliente_autenticado, avisos_falsos, app, dados):
    await checar_negada(cliente_autenticado, app, avisos_falsos, dados,
                        {"nome": "x\nmotivo: ok.md", "conteudo": "x"},
                        "fora_da_inbox", MENSAGENS["fora_da_inbox"])
    linhas = avisos_falsos.enviados[-1]["detalhes"].split("\n")
    assert len(linhas) == 3 and linhas[-1] == "motivo: fora_da_inbox"


async def test_criar_nota_ja_existe_grave(cliente_autenticado, avisos_falsos, app, dados):
    args = {"nome": "T.md", "conteudo": "x"}
    await chamar(cliente_autenticado, "criar_nota", args)
    await checar_negada(cliente_autenticado, app, avisos_falsos, dados, args,
                        "ja_existe", MENSAGENS["ja_existe"])
    assert (dados / "inbox" / "T.md").read_text() == "x"


async def test_criar_nota_conteudo_invalido_grave(cliente_autenticado, avisos_falsos, app, dados):
    await checar_negada(cliente_autenticado, app, avisos_falsos, dados,
                        {"nome": "T.md", "conteudo": ""}, "conteudo_invalido",
                        MENSAGENS["conteudo_invalido"])


@pytest.mark.parametrize("args", [{"nome": "x.md"}, {"nome": 1, "conteudo": "x"}])
async def test_criar_nota_argumentos_invalidos_grave(cliente_autenticado, avisos_falsos, app, dados, args):
    await checar_negada(cliente_autenticado, app, avisos_falsos, dados, args,
                        "argumentos_invalidos", "Argumentos inválidos.")


async def test_ler_com_argumento_faltando_continua_sem_alerta(cliente_autenticado, avisos_falsos, app, dados):
    res = await chamar(cliente_autenticado, "ler", {})
    assert res["isError"] is True and texto(res) == "Argumentos inválidos."
    await esperar(app)
    assert avisos_falsos.enviados == []
    assert linhas(dados / "logs/acesso.jsonl") == []


async def test_sem_inbox_json_leitura_funciona(cliente_autenticado, avisos_falsos, app, dados):
    (dados / "config/inbox.json").unlink()
    await checar_negada(cliente_autenticado, app, avisos_falsos, dados,
                        {"nome": "T.md", "conteudo": "x"}, "sem_permissao", MENSAGENS["sem_permissao"])
    res = await chamar(cliente_autenticado, "listar", {})
    assert not res.get("isError")


async def test_limpeza_ao_iniciar(vault, dados, token, avisos_falsos):
    (dados / "inbox").mkdir()
    velho = dados / "inbox" / "velha.md"
    velho.write_text("x")
    t = time.time() - 31 * 86400
    os.utime(velho, (t, t))
    app = criar_app(vault, dados, avisos=avisos_falsos)
    async with LifespanManager(app):
        pass
    assert not velho.exists()
