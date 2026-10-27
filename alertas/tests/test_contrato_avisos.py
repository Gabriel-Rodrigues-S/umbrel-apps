"""Contrato vault-gateway → alertas.

Cópia literal do montador de corpo de vault-gateway/vault_gateway/avisos.py
(limitar + corpo_json + cabeçalhos de Avisos._postar). Se mudar lá, mudar aqui.
Confere que o app aceita (201) os corpos no limite e que a origem vem do token.
"""
import json

import httpx
import pytest
from asgi_lifespan import LifespanManager

from alertas import remetentes
from alertas.main import criar_app

pytestmark = pytest.mark.anyio

# --- início da cópia de vault_gateway/avisos.py ---
MAX_TITULO = 120
MAX_DETALHES = 19000
MAX_CORPO = 60 * 1024
MARCA_CORTE = "… (cortado)"


def _txt(valor) -> str:
    s = valor if isinstance(valor, str) else str(valor)
    return s.encode("utf-8", "replace").decode("utf-8")


def _cortar(s: str, limite: int) -> str:
    if len(s) <= limite:
        return s
    return s[:max(0, limite - len(MARCA_CORTE))] + MARCA_CORTE


def corpo_json(corpo: dict) -> bytes:
    return json.dumps(corpo, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def limitar(gravidade, titulo, detalhes) -> dict:
    titulo = _cortar(_txt(titulo), MAX_TITULO) or "(sem título)"
    detalhes = _cortar(_txt(detalhes), MAX_DETALHES)
    corpo = {"gravidade": _txt(gravidade), "titulo": titulo, "detalhes": detalhes}
    while len(corpo_json(corpo)) > MAX_CORPO and corpo["detalhes"]:
        excesso = len(corpo_json(corpo)) / MAX_CORPO
        novo = int(len(corpo["detalhes"]) / excesso * 0.95) - 1
        corpo["detalhes"] = _cortar(corpo["detalhes"], max(len(MARCA_CORTE), novo))
        if novo <= len(MARCA_CORTE):
            corpo["detalhes"] = MARCA_CORTE
            break
    return corpo


def cabecalhos(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
# --- fim da cópia ---


@pytest.fixture
def dados(tmp_path):
    d = tmp_path / "dados"
    (d / "config").mkdir(parents=True)
    return d


@pytest.fixture
async def ambiente(dados):
    tokens = {n: remetentes.criar(dados / "config/remetentes.json", n) for n in ("gateway", "historico")}
    app = criar_app(dados, ip_host="10.21.0.1", usuario_permitido="g@x", enviar_push=lambda g: None)
    async with LifespanManager(app) as m:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(m.app, client=("10.21.0.7", 5)),
                                     base_url="http://alertas.teste") as c:
            yield c, tokens, m.app


async def listar(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("10.21.0.1", 5)),
                                 base_url="http://alertas.teste") as c:
        return (await c.get("/api/alertas", headers={"Tailscale-User-Login": "g@x"})).json()


@pytest.mark.parametrize("remetente", ["gateway", "historico"])
@pytest.mark.parametrize("letra", ["a", "ç", "😀", "\x01", "\ud800"])
async def test_corpo_no_limite_e_aceito_e_origem_vem_do_token(ambiente, remetente, letra):
    c, tokens, app = ambiente
    corpo = limitar("grave", letra * 500, letra * 50000)
    r = await c.post("/api/alertas", content=corpo_json(corpo), headers=cabecalhos(tokens[remetente]))
    assert r.status_code == 201, r.text
    [a] = await listar(app)
    assert a["origem"] == remetente
    assert a["titulo"] == corpo["titulo"] and a["detalhes"] == corpo["detalhes"]


async def test_corpo_curto_identico(ambiente):
    c, tokens, app = ambiente
    corpo = limitar("info", "Resumo diário", "Tentativas: 0")
    r = await c.post("/api/alertas", content=corpo_json(corpo), headers=cabecalhos(tokens["gateway"]))
    assert r.status_code == 201
    [a] = await listar(app)
    assert (a["origem"], a["gravidade"], a["titulo"]) == ("gateway", "info", "Resumo diário")


async def test_titulo_vazio_e_substituido_e_aceito(ambiente):
    c, tokens, app = ambiente
    r = await c.post("/api/alertas", content=corpo_json(limitar("normal", "", "")),
                     headers=cabecalhos(tokens["historico"]))
    assert r.status_code == 201


def test_copia_bate_com_o_original():
    """Se o repositório inteiro estiver presente, a cópia acima tem de bater com avisos.py."""
    import inspect
    from pathlib import Path

    original = Path(__file__).resolve().parents[2] / "vault-gateway/vault_gateway/avisos.py"
    if not original.exists():
        pytest.skip("vault-gateway fora deste checkout")
    fonte = original.read_text(encoding="utf-8")
    for linha in ("MAX_TITULO = 120", "MAX_DETALHES = 19000", "MAX_CORPO = 60 * 1024",
                  'MARCA_CORTE = "… (cortado)"',
                  'json.dumps(corpo, ensure_ascii=False, separators=(",", ":")).encode("utf-8")',
                  '"Content-Type": "application/json"'):
        assert linha in fonte, linha
    for linha in ("return s[:max(0, limite - len(MARCA_CORTE))] + MARCA_CORTE",
                  'titulo = _cortar(_txt(titulo), MAX_TITULO) or "(sem título)"',
                  "detalhes = _cortar(_txt(detalhes), MAX_DETALHES)",
                  "while len(corpo_json(corpo)) > MAX_CORPO and corpo[\"detalhes\"]:"):
        assert linha in fonte, linha
