import json

import httpx
import pytest

from vault_gateway import avisos as mod
from vault_gateway.avisos import MARCA_CORTE, Avisos, avisos_de_config, corpo_json, limitar


def pendentes(fila):
    return sorted(fila.glob("*.json")) if fila.exists() else []


def cliente_com(fn):
    return httpx.Client(transport=httpx.MockTransport(fn))


def test_aviso_vai_para_fila_quando_alertas_cai(tmp_path):
    a = Avisos("http://127.0.0.1:9", "t", tmp_path / "fila")
    a.enviar("grave", "x", "y")  # não lança
    arquivos = pendentes(tmp_path / "fila")
    assert len(arquivos) == 1
    dado = json.loads(arquivos[0].read_text())
    assert dado["gravidade"] == "grave" and dado["titulo"] == "x" and dado["detalhes"] == "y" and dado["criado_em"]
    assert "t" != dado.get("token")


def test_reenvio_esvazia_fila(tmp_path, servidor_falso):
    a = Avisos(servidor_falso.url, "t", tmp_path / "fila", cliente=servidor_falso.cliente)
    a.enviar("normal", "x", "y")
    assert len(pendentes(tmp_path / "fila")) == 1
    servidor_falso.ligar()
    assert a.reenviar_fila() == 1
    assert pendentes(tmp_path / "fila") == []


def test_envio_ok_apaga_da_fila_e_manda_bearer_e_corpo(tmp_path, servidor_falso):
    servidor_falso.ligar()
    a = Avisos(servidor_falso.url, "segredo", tmp_path / "fila", cliente=servidor_falso.cliente)
    a.enviar("info", "t", "d")
    assert pendentes(tmp_path / "fila") == []
    req = servidor_falso.recebidos[0]
    assert req.headers["authorization"] == "Bearer segredo"
    assert req.headers["content-type"] == "application/json"
    assert json.loads(req.content) == {"gravidade": "info", "titulo": "t", "detalhes": "d"}


def test_fila_primeiro_grava_antes_da_rede(tmp_path):
    """No momento do POST o aviso já está no disco (sobrevive a SIGKILL)."""
    fila = tmp_path / "fila"
    visto = []

    def h(req):
        visto.append(len(pendentes(fila)))
        return httpx.Response(201)

    a = Avisos("http://x", "t", fila, cliente=cliente_com(h))
    a.enviar("grave", "a", "b")
    assert visto == [1] and pendentes(fila) == []


def test_guardar_nao_usa_rede(tmp_path):
    def h(req):
        raise AssertionError("não deveria postar")

    a = Avisos("http://x", "t", tmp_path / "fila", cliente=cliente_com(h))
    assert a.guardar("grave", "a", "b") is True
    assert len(pendentes(tmp_path / "fila")) == 1


@pytest.mark.parametrize("status", [500, 503, 401, 403, 404, 405, 408, 429])
def test_falha_temporaria_fica_na_fila(tmp_path, status):
    a = Avisos("http://x", "t", tmp_path / "fila", cliente=cliente_com(lambda r: httpx.Response(status)))
    a.enviar("grave", "a", "b")
    assert len(pendentes(tmp_path / "fila")) == 1
    assert not (tmp_path / "fila" / "invalidos").exists()


@pytest.mark.parametrize("status", [400, 413, 422])
def test_recusa_definitiva_vai_para_invalidos_e_segue(tmp_path, status, capsys):
    fila = tmp_path / "fila"
    estado = {"n": 0, "titulos": []}

    def h(req):
        estado["n"] += 1
        estado["titulos"].append(json.loads(req.content)["titulo"])
        return httpx.Response(status if estado["n"] == 1 else 201)

    a = Avisos("http://x", "t", fila, cliente=cliente_com(h))
    for n in range(3):
        a.guardar("normal", f"t{n}", "d")
    assert a.reenviar_fila() == 2
    assert estado["titulos"] == ["t0", "t1", "t2"]
    assert pendentes(fila) == []
    assert len(list((fila / "invalidos").glob("*.json"))) == 1
    assert "invalidos" in capsys.readouterr().err


def test_reenvio_para_no_primeiro_erro_e_mantem_ordem(tmp_path):
    estado = {"ok": False, "titulos": []}

    def h(req):
        if not estado["ok"]:
            raise httpx.ConnectError("x", request=req)
        estado["titulos"].append(json.loads(req.content)["titulo"])
        return httpx.Response(201)

    a = Avisos("http://x", "t", tmp_path / "fila", cliente=cliente_com(h))
    for n in range(3):
        a.enviar("normal", f"t{n}", "d")
    assert a.reenviar_fila() == 0 and len(pendentes(tmp_path / "fila")) == 3
    estado["ok"] = True
    assert a.reenviar_fila() == 3
    assert estado["titulos"] == ["t0", "t1", "t2"]


def test_reenvio_para_apos_falha_no_meio(tmp_path):
    chamadas = []

    def h(req):
        chamadas.append(1)
        if len(chamadas) == 2:
            return httpx.Response(503)
        return httpx.Response(201)

    a = Avisos("http://x", "t", tmp_path / "fila", cliente=cliente_com(h))
    for n in range(3):
        a.guardar("normal", f"t{n}", "d")
    assert a.reenviar_fila() == 1
    assert len(pendentes(tmp_path / "fila")) == 2


def test_arquivo_corrompido_vai_para_invalidos(tmp_path, servidor_falso):
    fila = tmp_path / "fila"
    fila.mkdir()
    (fila / "0-lixo.json").write_text("{nao é json")
    (fila / "1-gravidade.json").write_text(json.dumps({"gravidade": "x", "titulo": "a", "detalhes": ""}))
    servidor_falso.ligar()
    a = Avisos(servidor_falso.url, "t", fila, cliente=servidor_falso.cliente)
    a.guardar("normal", "z", "w")
    assert a.reenviar_fila() == 1
    assert (fila / "invalidos" / "0-lixo.json").exists()
    assert (fila / "invalidos" / "1-gravidade.json").exists()
    assert not (fila / "0-lixo.json").exists()


def test_token_nao_aparece_na_fila_nem_no_stderr(tmp_path, capsys):
    a = Avisos("http://127.0.0.1:9", "TOKEN-SECRETO", tmp_path / "fila")
    a.enviar("grave", "x", "y")
    a.reenviar_fila()
    saida = capsys.readouterr()
    assert "TOKEN-SECRETO" not in saida.out + saida.err
    for f in (tmp_path / "fila").iterdir():
        assert "TOKEN-SECRETO" not in f.read_text()


def test_nunca_lanca_mesmo_sem_poder_gravar_fila(tmp_path, capsys):
    bloqueio = tmp_path / "arquivo"
    bloqueio.write_text("x")  # fila aponta para dentro de um arquivo
    a = Avisos("http://127.0.0.1:9", "t", bloqueio / "fila")
    a.enviar("grave", "x", "y")
    assert a.reenviar_fila() == 0
    assert "aviso perdido" in capsys.readouterr().err


# --- limites do app de alertas ---

def test_titulo_e_detalhes_cortados_ao_gravar(tmp_path):
    a = Avisos("", "", tmp_path / "fila")
    a.guardar("grave", "T" * 500, "d" * 50000)
    dado = json.loads(pendentes(tmp_path / "fila")[0].read_text())
    assert len(dado["titulo"]) == 120 and dado["titulo"].endswith(MARCA_CORTE)
    assert len(dado["detalhes"]) <= 19000 and dado["detalhes"].endswith(MARCA_CORTE)


@pytest.mark.parametrize("letra", ["a", "ç", "😀", "\x01", "\ud800"])
def test_corpo_sempre_cabe_em_64_kib(letra):
    c = limitar("grave", letra * 500, letra * 30000)
    assert len(corpo_json(c)) <= 60 * 1024
    assert 1 <= len(c["titulo"]) <= 120 and len(c["detalhes"]) <= 20000
    json.loads(corpo_json(c))


def test_titulo_vazio_ganha_substituto():
    assert limitar("info", "", "")["titulo"] == "(sem título)"


def test_fila_cheia_descarta_info_e_normal_mas_guarda_grave(tmp_path, capsys):
    a = Avisos("", "", tmp_path / "fila", max_fila=3)
    for n in range(3):
        assert a.guardar("info", f"i{n}", "")
    assert a.guardar("normal", "n", "") is False
    assert a.guardar("info", "i", "") is False
    assert a.guardar("grave", "g", "") is True
    assert len(pendentes(tmp_path / "fila")) == 4
    assert "fila cheia" in capsys.readouterr().err


def test_modo_so_fila_nao_posta(tmp_path):
    a = Avisos("", "", tmp_path / "fila", cliente=cliente_com(lambda r: (_ for _ in ()).throw(AssertionError)))
    a.enviar("grave", "a", "b")
    assert a.reenviar_fila() == 0
    assert len(pendentes(tmp_path / "fila")) == 1


# --- configuração por remetente ---

def _cfg(dados, cfg):
    (dados / "config").mkdir(parents=True, exist_ok=True)
    (dados / "config/avisos.json").write_text(json.dumps(cfg))


@pytest.mark.parametrize("remetente", ["gateway", "historico"])
def test_cada_servico_usa_seu_token_e_sua_fila(tmp_path, remetente, monkeypatch):
    _cfg(tmp_path, {"url": "http://alertas.teste/api/alertas",
                    "tokens": {"gateway": "TG", "historico": "TH"}})
    monkeypatch.setenv("REMETENTE", remetente)
    a = avisos_de_config(tmp_path)
    assert a._token == {"gateway": "TG", "historico": "TH"}[remetente]
    assert a._fila == tmp_path / "fila-avisos" / remetente
    assert a._url == "http://alertas.teste/api/alertas"


@pytest.mark.parametrize("valor", [None, "", "conferencia-pc", "../x"])
def test_remetente_ausente_ou_desconhecido_so_fila(tmp_path, valor, monkeypatch, capsys):
    _cfg(tmp_path, {"url": "http://x", "tokens": {"gateway": "TG", "historico": "TH"}})
    if valor is None:
        monkeypatch.delenv("REMETENTE", raising=False)
    else:
        monkeypatch.setenv("REMETENTE", valor)
    a = avisos_de_config(tmp_path)
    assert a._token == "" and a._url == ""
    assert a._fila == tmp_path / "fila-avisos" / "sem-remetente"
    assert "REMETENTE" in capsys.readouterr().err


def test_sem_token_do_proprio_servico_nao_usa_o_do_outro(tmp_path, monkeypatch, capsys):
    _cfg(tmp_path, {"url": "http://x", "tokens": {"gateway": "TG"}})
    monkeypatch.setenv("REMETENTE", "historico")
    a = avisos_de_config(tmp_path)
    assert a._token == "" and a._fila == tmp_path / "fila-avisos" / "historico"
    assert "avisos.json" in capsys.readouterr().err


def test_formato_antigo_com_token_unico_e_recusado(tmp_path, monkeypatch):
    _cfg(tmp_path, {"url": "http://x", "token": "T"})
    monkeypatch.setenv("REMETENTE", "gateway")
    assert avisos_de_config(tmp_path)._token == ""


def test_limites_batem_com_o_app_de_alertas():
    assert mod.MAX_TITULO == 120 and mod.MAX_DETALHES < 20000 and mod.MAX_CORPO < 64 * 1024
