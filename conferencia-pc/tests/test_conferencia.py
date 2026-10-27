import hashlib
import json
import os
import subprocess
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import conferencia
from conferencia import (
    SshIndisponivel,
    decidir,
    diferencas,
    main,
    parse_sha256sum,
    somas_locais,
    somas_remotas,
)


def sha(t: bytes) -> str:
    return hashlib.sha256(t).hexdigest()


# ---- somas_locais ----
def test_ignora_obsidian(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian/w.json").write_text("x")
    (tmp_path / "n.md").write_text("y")
    assert set(somas_locais(tmp_path)) == {"n.md"}


def test_ignora_pastas_aninhadas(tmp_path):
    for p in ["a/.obsidian", "a/b/.git", "c/.trash"]:
        (tmp_path / p).mkdir(parents=True)
        (tmp_path / p / "f.txt").write_text("z")
    (tmp_path / "a/ok.md").write_text("ok")
    assert set(somas_locais(tmp_path)) == {"a/ok.md"}


def test_somas_locais_hash_e_chave_nfc(tmp_path):
    nfd = unicodedata.normalize("NFD", "Referências/é.md")
    (tmp_path / nfd).parent.mkdir()
    (tmp_path / nfd).write_bytes(b"conteudo")
    r = somas_locais(tmp_path)
    assert list(r) == [unicodedata.normalize("NFC", "Referências/é.md")]
    assert r["Referências/é.md"] == sha(b"conteudo")


def test_somas_locais_pula_ilegivel(tmp_path, capsys):
    f = tmp_path / "x.md"
    f.write_text("a")
    (tmp_path / "y.md").write_text("b")
    f.chmod(0)
    try:
        if os.access(f, os.R_OK):
            pytest.skip("root le tudo")
        r = somas_locais(tmp_path)
    finally:
        f.chmod(0o600)
    assert set(r) == {"y.md"}
    assert "x.md" in capsys.readouterr().err


def test_somas_locais_nao_segue_links(tmp_path):
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "z.md").write_text("z")
    v = tmp_path / "v"
    v.mkdir()
    (v / "l").symlink_to(ext)
    assert somas_locais(v) == {}


# ---- parse ----
def test_parse_sha256sum_basico_e_prefixo():
    h = "a" * 64
    out = f"{h}  ./a/b c.md\n{h}  ./Referências/x.md\n"
    r = parse_sha256sum(out)
    assert r == {"a/b c.md": h, "Referências/x.md": h}


def test_parse_nfc():
    h = "b" * 64
    nfd = unicodedata.normalize("NFD", "é.md")
    r = parse_sha256sum(f"{h}  ./{nfd}\n")
    assert list(r) == [unicodedata.normalize("NFC", "é.md")]


def test_parse_nomes_escapados():
    h = "c" * 64
    out = f"\\{h}  ./a\\\\b.md\n\\{h}  ./nova\\nlinha.md\n{h}  ./ok.md\n"
    r = parse_sha256sum(out)
    assert r["a\\b.md"] == h
    assert r["nova\nlinha.md"] == h
    assert r["ok.md"] == h


def test_parse_ignora_linhas_invalidas():
    assert parse_sha256sum("lixo\n\n") == {}


# ---- somas_remotas ----
def test_somas_remotas_argv():
    h = "d" * 64
    chamadas = []

    def runner(argv, **kw):
        chamadas.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, stdout=f"{h}  ./n.md\n", stderr="")

    r = somas_remotas("srv", "/dados/meu vault; rm -rf x", runner=runner)
    assert r == {"n.md": h}
    assert len(chamadas) == 1
    argv, kw = chamadas[0]
    assert isinstance(argv, list)
    assert argv[0] == "ssh"
    assert argv[argv.index("-o") + 1] == "BatchMode=yes"
    assert "ConnectTimeout=10" in argv
    assert "srv" in argv
    assert kw.get("shell") in (None, False)
    assert kw["timeout"] == 300
    cmd = argv[-1]
    assert "cd '/dados/meu vault; rm -rf x' &&" in cmd
    assert "find . -type f" in cmd
    assert "-exec sha256sum {} +" in cmd
    for nome in (".obsidian", ".git", ".trash"):
        assert f"-not -path './{nome}/*'" in cmd
        assert f"-not -path '*/{nome}/*'" in cmd


@pytest.mark.parametrize("modo", ["rc", "timeout", "nossh"])
def test_somas_remotas_falha(modo):
    def runner(argv, **kw):
        if modo == "timeout":
            raise subprocess.TimeoutExpired(argv, 300)
        if modo == "nossh":
            raise OSError("sem ssh")
        return subprocess.CompletedProcess(argv, 255, stdout="", stderr="boom")

    with pytest.raises(SshIndisponivel):
        somas_remotas("srv", "/x", runner=runner)


# ---- diferencas ----
def test_diferencas():
    a = {"a": "1", "b": "2", "c": "3"}
    b = {"b": "2", "c": "9", "d": "4"}
    assert diferencas(a, b) == ["a", "c", "d"]
    assert diferencas(a, a) == []


# ---- decidir ----
def test_so_alerta_na_segunda_vez(tmp_path):
    assert decidir(["a.md"], tmp_path / "e.json") is False
    assert decidir(["a.md"], tmp_path / "e.json") is True
    assert decidir([], tmp_path / "e.json") is False


def test_decidir_divergencia_diferente(tmp_path):
    e = tmp_path / "e.json"
    assert decidir(["a"], e) is False
    assert decidir(["a", "b"], e) is False
    assert decidir(["b", "a"], e) is True
    assert json.loads(e.read_text()) == {"anterior": ["a", "b"]}


def test_decidir_estado_corrompido(tmp_path):
    e = tmp_path / "e.json"
    e.write_text("{nao json")
    assert decidir(["a"], e) is False
    assert decidir(["a"], e) is True


def test_decidir_cria_diretorio(tmp_path):
    e = tmp_path / "x/y/e.json"
    decidir(["a"], e)
    assert e.exists()


# ---- main ----
CFG = {
    "ssh_host": "srv",
    "caminho_remoto": "/r",
    "url_alertas": "http://x/api",
}


@pytest.fixture
def amb(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("a")
    (cfg / "config.json").write_text(json.dumps({**CFG, "caminho_local": str(vault)}))
    t = cfg / "token"
    t.write_text("segredo-xyz\n")
    t.chmod(0o600)
    return {"config_dir": cfg, "estado": tmp_path / "st/estado.json", "vault": vault}


def diverge(*a, **k):
    return {"a.md": "0" * 64}


def test_main_token_permissivo(amb, capsys):
    (amb["config_dir"] / "token").chmod(0o640)
    rc = main(**amb, somas_remotas_fn=diverge, enviar_fn=lambda *a: pytest.fail("enviou"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "token" in err and "segredo-xyz" not in err
    assert not amb["estado"].exists()


def test_main_inacessivel_nao_alerta_nem_grava(amb, capsys):
    def falha(*a, **k):
        raise SshIndisponivel("fora")

    rc = main(**amb, somas_remotas_fn=falha, enviar_fn=lambda *a: pytest.fail("enviou"))
    assert rc == 0
    assert capsys.readouterr().err.strip()
    assert not amb["estado"].exists()


def test_main_alerta_na_segunda(amb):
    enviados = []
    kw = dict(**amb, somas_remotas_fn=diverge, enviar_fn=lambda *a: enviados.append(a))
    assert main(**kw) == 0
    assert enviados == []
    assert main(**kw) == 0
    assert len(enviados) == 1
    url, token, diffs = enviados[0]
    assert url == "http://x/api" and token == "segredo-xyz" and diffs == ["a.md"]


def test_main_sem_divergencia(amb):
    from conferencia import somas_locais as sl

    iguais = lambda *a, **k: sl(amb["vault"])
    enviados = []
    kw = dict(**amb, somas_remotas_fn=iguais, enviar_fn=lambda *a: enviados.append(a))
    main(**kw)
    main(**kw)
    assert enviados == []


def test_main_post_falha_exit1(amb, capsys):
    def ruim(*a):
        raise OSError("rede")

    kw = dict(**amb, somas_remotas_fn=diverge, enviar_fn=ruim)
    main(**kw)
    assert main(**kw) == 1
    err = capsys.readouterr().err
    assert err.strip() and "segredo-xyz" not in err


def test_main_config_ausente(tmp_path, capsys):
    assert main(config_dir=tmp_path / "nada", estado=tmp_path / "e.json") == 2
    assert capsys.readouterr().err.strip()


# ---- enviar_alerta / corpo ----
def test_corpo_limita_200():
    paths = [f"p{i}.md" for i in range(250)]
    c = conferencia.montar_corpo(paths)
    assert c["gravidade"] == "normal"
    assert c["titulo"] == "Cópias do vault divergentes"
    linhas = c["detalhes"].split("\n")
    assert linhas[:200] == paths[:200]
    assert linhas[200] == "… e mais 50"
    assert len(linhas) == 201


def test_corpo_curto():
    assert conferencia.montar_corpo(["a", "b"])["detalhes"] == "a\nb"


def test_post_real_headers_e_corpo():
    recebido = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            recebido["body"] = self.rfile.read(n)
            recebido["auth"] = self.headers["Authorization"]
            recebido["ct"] = self.headers["Content-Type"]
            self.send_response(201)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        conferencia.enviar_alerta(f"http://127.0.0.1:{srv.server_port}/a", "tok", ["x é.md"])
    finally:
        srv.shutdown()
    assert recebido["auth"] == "Bearer tok"
    assert recebido["ct"].startswith("application/json")
    body = json.loads(recebido["body"].decode("utf-8"))
    assert body == {
        "gravidade": "normal",
        "titulo": "Cópias do vault divergentes",
        "detalhes": "x é.md",
    }


def test_post_erro_http_levanta():
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(500)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(Exception):
            conferencia.enviar_alerta(f"http://127.0.0.1:{srv.server_port}/a", "t", ["a"])
    finally:
        srv.shutdown()
