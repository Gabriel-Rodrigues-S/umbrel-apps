import hashlib
import json
import os
import shlex
import subprocess

import pytest

import coleta
from coleta import SshIndisponivel, coletar, listar_remoto, main, nome_valido

CFG = {"ssh_host": "umbrel@umbrel.local", "caminho_remoto": "/r/inbox"}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Remoto:
    """Runner falso: serve um dict {nome: bytes} como o servidor faria."""

    def __init__(self, arquivos, listados=None):
        self.arquivos = arquivos
        self.listados = listados  # nome -> sha a anunciar (força divergência)
        self.chamadas = []

    def __call__(self, argv, **kw):
        assert argv[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        assert argv[5] == "--"
        cmd = argv[7]
        self.chamadas.append(cmd)
        if "sha256sum -z" in cmd:
            out = b""
            for n, d in self.arquivos.items():
                h = (self.listados or {}).get(n, sha(d))
                out += f"{h}  ./{n}".encode() + b"\0"
            return subprocess.CompletedProcess(argv, 0, out, b"")
        partes = shlex.split(cmd)
        assert partes[:4] == ["head", "-c", "102401", "--"]
        nome = partes[4].rsplit("/", 1)[1]
        return subprocess.CompletedProcess(argv, 0, self.arquivos[nome][:102401], b"")


@pytest.fixture
def amb(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = dict(CFG, caminho_local=str(vault))
    return cfg, vault, tmp_path / "estado" / "c.json"


def test_coleta_grava_nova_nota(amb):
    cfg, vault, est = amb
    assert coletar(cfg, est, Remoto({"R.md": b"# r\n"})) == 1
    assert (vault / "Inbox/R.md").read_bytes() == b"# r\n"
    assert oct((vault / "Inbox/R.md").stat().st_mode & 0o777) == oct(0o644 & ~os.umask(0))


def test_nao_recopia(amb):
    cfg, vault, est = amb
    r = Remoto({"R.md": b"# r\n"})
    assert coletar(cfg, est, r) == 1
    (vault / "Inbox/R.md").unlink()
    assert coletar(cfg, est, r) == 0
    assert not (vault / "Inbox/R.md").exists()


def test_nome_reaproveitado_com_outro_conteudo_coleta_de_novo(amb):
    cfg, vault, est = amb
    coletar(cfg, est, Remoto({"R.md": b"um\n"}))
    assert coletar(cfg, est, Remoto({"R.md": b"dois\n"})) == 1
    assert (vault / "Inbox/R.md").read_bytes() == b"um\n"
    assert (vault / "Inbox/R-2.md").read_bytes() == b"dois\n"


def test_estado_esquece_o_que_sumiu_do_servidor(amb):
    cfg, vault, est = amb
    coletar(cfg, est, Remoto({"R.md": b"a\n", "S.md": b"b\n"}))
    coletar(cfg, est, Remoto({"S.md": b"b\n"}))
    nomes = [e["nome"] for e in json.loads(est.read_text())["coletados"]]
    assert nomes == ["S.md"]


def test_estado_formato(amb):
    cfg, vault, est = amb
    coletar(cfg, est, Remoto({"R.md": b"a\n"}))
    (e,) = json.loads(est.read_text())["coletados"]
    assert set(e) == {"nome", "sha256", "gravado", "quando"}
    assert e["sha256"] == sha(b"a\n") and e["gravado"] == "R.md"


@pytest.mark.parametrize("existente", ["R.md", "r.md"])
def test_existente_no_pc_vira_sufixo(amb, existente):
    cfg, vault, est = amb
    (vault / "Inbox").mkdir()
    (vault / "Inbox" / existente).write_bytes(b"meu\n")
    assert coletar(cfg, est, Remoto({"R.md": b"novo\n"})) == 1
    assert (vault / "Inbox" / existente).read_bytes() == b"meu\n"
    assert (vault / "Inbox/R-2.md").read_bytes() == b"novo\n"


@pytest.mark.parametrize("nome", ["../x.md", "a/b.md", "x.txt", ".x.md"])
def test_nome_perigoso_ignorado(amb, nome):
    cfg, vault, est = amb
    assert coletar(cfg, est, Remoto({nome: b"x\n"})) == 0
    assert [p for p in vault.parent.rglob("*") if p.is_file() and p != est] == []


@pytest.mark.parametrize("dados", [b"a" * 102_401, b"\xff", b"a\x00", b""])
def test_conteudo_grande_ou_binario_ignorado(amb, dados):
    cfg, vault, est = amb
    assert coletar(cfg, est, Remoto({"R.md": dados})) == 0
    assert not (vault / "Inbox").exists() or not list((vault / "Inbox").iterdir())


def test_conteudo_no_limite_vale(amb):
    cfg, vault, est = amb
    assert coletar(cfg, est, Remoto({"R.md": b"a" * 102_400})) == 1


def test_sha_diferente_do_listado_ignorado(amb):
    cfg, vault, est = amb
    r = Remoto({"R.md": b"a\n"}, listados={"R.md": "0" * 64})
    assert coletar(cfg, est, r) == 0
    assert not est.exists()


def test_inbox_link_simbolico_nao_grava(amb):
    cfg, vault, est = amb
    fora = vault.parent / "fora"
    fora.mkdir()
    (vault / "Inbox").symlink_to(fora)
    assert coletar(cfg, est, Remoto({"R.md": b"a\n"})) == 0
    assert list(fora.iterdir()) == []


def test_gravar_exclusivo_recusa_link(tmp_path):
    fora = tmp_path / "fora"
    fora.mkdir()
    (tmp_path / "Inbox").symlink_to(fora)
    with pytest.raises(OSError):
        coleta.gravar_exclusivo(tmp_path / "Inbox", "R.md", b"a")
    assert list(fora.iterdir()) == []


def test_cria_pasta_inbox(amb):
    cfg, vault, est = amb
    assert not (vault / "Inbox").exists()
    coletar(cfg, est, Remoto({"R.md": b"a\n"}))
    assert (vault / "Inbox").is_dir()


def test_maximo_20_por_execucao(amb):
    cfg, vault, est = amb
    r = Remoto({f"N{i:02}.md": b"x%d\n" % i for i in range(25)})
    assert coletar(cfg, est, r) == 20
    assert coletar(cfg, est, r) == 5
    assert len(list((vault / "Inbox").iterdir())) == 25


def test_ssh_indisponivel_sai_0_sem_tocar_estado(tmp_path):
    cfgdir = tmp_path / "cfg"
    cfgdir.mkdir()
    (cfgdir / "config.json").write_text(json.dumps(dict(CFG, caminho_local=str(tmp_path))))
    est = tmp_path / "est.json"
    est.write_text('{"coletados": []}')
    antes = est.read_bytes()

    def run(argv, **kw):
        return subprocess.CompletedProcess(argv, 255, b"", b"")

    assert main(cfgdir, est, run) == 0
    assert est.read_bytes() == antes


@pytest.mark.parametrize("exc", [subprocess.TimeoutExpired("ssh", 1), FileNotFoundError("ssh")])
def test_timeout_e_oserror_viram_indisponivel(exc):
    def run(argv, **kw):
        raise exc

    with pytest.raises(SshIndisponivel):
        listar_remoto("h", "/r", run)


def test_comando_remoto_falho_sai_1_sem_tocar_estado(tmp_path, capsys):
    cfgdir = tmp_path / "cfg"
    cfgdir.mkdir()
    (cfgdir / "config.json").write_text(json.dumps(dict(CFG, caminho_local=str(tmp_path))))
    est = tmp_path / "est.json"

    def run(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, b"", b"x")

    assert main(cfgdir, est, run) == 1
    assert not est.exists()
    assert "falhou" in capsys.readouterr().err


def test_config_ausente_sai_1(tmp_path, capsys):
    assert main(tmp_path / "nada", tmp_path / "e.json") == 1
    assert "configuração" in capsys.readouterr().err


def test_main_ok(tmp_path):
    vault = tmp_path / "v"
    vault.mkdir()
    cfgdir = tmp_path / "cfg"
    cfgdir.mkdir()
    (cfgdir / "config.json").write_text(json.dumps(dict(CFG, caminho_local=str(vault))))
    assert main(cfgdir, tmp_path / "e.json", Remoto({"R.md": b"a\n"})) == 0
    assert (vault / "Inbox/R.md").exists()


def test_parse_nome_com_espaco_e_acento():
    nome = "Relatório (nov).md"
    saida = f"{sha(b'x')}  ./{nome}".encode() + b"\0"
    assert listar_remoto("h", "/r", lambda a, **k: subprocess.CompletedProcess(a, 0, saida, b"")) == {nome: sha(b"x")}


def test_comando_listar_e_baixar_com_aspas():
    vistos = []

    def run(argv, **kw):
        vistos.append(argv[7])
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    listar_remoto("h", "/a b/inbox", run)
    coleta.baixar("h", "/a b/inbox", "N 1.md", run)
    assert vistos[0].startswith("cd -- '/a b/inbox' && find . -maxdepth 1 -type f ! -name '.*' -print0 | xargs -0 -r sha256sum -z")
    assert vistos[1] == "head -c 102401 -- '/a b/inbox/N 1.md'"


@pytest.mark.parametrize("nome,ok", [
    ("Nota.md", True), ("Relatório (nov).md", True), ("a b-c_d.md", True),
    ("x.MD", False), ("a .md", False), (" a.md", False), ("a..b.md", False),
    ("a/b.md", False), ("a\\b.md", False), ("a\x00.md", False), ("a\n.md", False),
    ("a" * 98 + ".md", False), ("a" * 97 + ".md", True), ("a$.md", False), (".md", False),
])
def test_nome_valido(nome, ok):
    assert (nome_valido(nome) is not None) is ok


def test_nome_acima_de_255_bytes_e_invalido():
    assert nome_valido("界" * 97 + ".md") is None
    assert nome_valido("a" * 97 + ".md") is not None


def test_nome_valido_devolve_nfc():
    import unicodedata
    assert nome_valido(unicodedata.normalize("NFD", "ç.md")) == unicodedata.normalize("NFC", "ç.md")
