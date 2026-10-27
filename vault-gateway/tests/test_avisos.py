import json

import httpx

from vault_gateway.avisos import Avisos


def test_aviso_vai_para_fila_quando_alertas_cai(tmp_path):
    a = Avisos("http://127.0.0.1:9", "t", tmp_path / "fila")
    a.enviar("grave", "x", "y")  # não lança
    arquivos = list((tmp_path / "fila").iterdir())
    assert len(arquivos) == 1
    dado = json.loads(arquivos[0].read_text())
    assert dado["gravidade"] == "grave" and dado["titulo"] == "x" and dado["detalhes"] == "y" and dado["criado_em"]
    assert "t" != dado.get("token")


def test_reenvio_esvazia_fila(tmp_path, servidor_falso):
    a = Avisos(servidor_falso.url, "t", tmp_path / "fila", cliente=servidor_falso.cliente)
    a.enviar("normal", "x", "y")
    assert len(list((tmp_path / "fila").glob("*.json"))) == 1
    servidor_falso.ligar()
    assert a.reenviar_fila() == 1
    assert list((tmp_path / "fila").glob("*.json")) == []


def test_envio_ok_nao_usa_fila_e_manda_bearer_e_corpo(tmp_path, servidor_falso):
    servidor_falso.ligar()
    a = Avisos(servidor_falso.url, "segredo", tmp_path / "fila", cliente=servidor_falso.cliente)
    a.enviar("info", "t", "d")
    assert not (tmp_path / "fila").exists() or list((tmp_path / "fila").iterdir()) == []
    req = servidor_falso.recebidos[0]
    assert req.headers["authorization"] == "Bearer segredo"
    assert json.loads(req.content) == {"gravidade": "info", "titulo": "t", "detalhes": "d"}


def test_resposta_nao_2xx_vai_para_fila(tmp_path):
    cli = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    a = Avisos("http://x", "t", tmp_path / "fila", cliente=cli)
    a.enviar("grave", "a", "b")
    assert len(list((tmp_path / "fila").glob("*.json"))) == 1


def test_reenvio_para_no_primeiro_erro_e_mantem_ordem(tmp_path):
    estado = {"ok": False, "titulos": []}

    def h(req):
        if not estado["ok"]:
            raise httpx.ConnectError("x", request=req)
        estado["titulos"].append(json.loads(req.content)["titulo"])
        return httpx.Response(201)

    a = Avisos("http://x", "t", tmp_path / "fila", cliente=httpx.Client(transport=httpx.MockTransport(h)))
    for n in range(3):
        a.enviar("normal", f"t{n}", "d")
    assert a.reenviar_fila() == 0 and len(list((tmp_path / "fila").glob("*.json"))) == 3
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

    cli = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    a = Avisos("http://x", "t", tmp_path / "fila", cliente=cli)
    for n in range(3):
        a.enviar("normal", f"t{n}", "d")
    a._cliente = httpx.Client(transport=httpx.MockTransport(h))
    assert a.reenviar_fila() == 1
    assert len(list((tmp_path / "fila").glob("*.json"))) == 2


def test_arquivo_corrompido_vai_para_invalidos(tmp_path, servidor_falso):
    fila = tmp_path / "fila"
    fila.mkdir()
    (fila / "0-lixo.json").write_text("{nao é json")
    servidor_falso.ligar()
    a = Avisos(servidor_falso.url, "t", fila, cliente=servidor_falso.cliente)
    a._guardar("normal", "z", "w")
    assert a.reenviar_fila() == 1
    assert (fila / "invalidos" / "0-lixo.json").exists()
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
