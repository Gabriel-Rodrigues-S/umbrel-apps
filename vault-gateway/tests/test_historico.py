import json
import re
import subprocess

import pytest

from vault_gateway.historico import (
    DetectorEnvio, Historico, commitar, ler_deteccao, mudancas_sem_download,
)


def vault_git(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    (v / "a.md").write_text("a")
    return v, tmp_path / "historico.git"


def git(g, v, *args):
    return subprocess.run(["git", "-c", "safe.directory=*", f"--git-dir={g}", f"--work-tree={v}", *args],
                          capture_output=True, text=True, check=True).stdout


def test_commit_so_quando_muda(tmp_path):
    v, g = vault_git(tmp_path)
    assert commitar(v, g) is True and commitar(v, g) is False
    (v / "n.md").write_text("x")
    assert commitar(v, g) is True


def test_git_dir_criado_no_primeiro_uso_e_vault_intocado(tmp_path):
    v, g = vault_git(tmp_path)
    (v / ".obsidian").mkdir()
    (v / ".obsidian" / "app.json").write_text("{}")
    (v / "Referências").mkdir()
    (v / "Referências" / "Nota com espaço.md").write_text("n")
    antes = sorted(p.relative_to(v).as_posix() for p in v.rglob("*"))
    assert not g.exists()
    assert commitar(v, g) is True
    assert g.is_dir()
    assert sorted(p.relative_to(v).as_posix() for p in v.rglob("*")) == antes  # nada novo (.git etc.)
    arquivos = git(g, v, "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "HEAD").split("\n")
    assert ".obsidian/app.json" in arquivos and "Referências/Nota com espaço.md" in arquivos
    assert git(g, v, "log", "-1", "--format=%an <%ae>|%s").startswith("historico <historico@localhost>|auto: ")


def test_vault_somente_leitura(tmp_path):
    v, g = vault_git(tmp_path)
    v.chmod(0o555)
    try:
        assert commitar(v, g) is True
    finally:
        v.chmod(0o755)


def test_modo_a_detecta_envio():
    d = DetectorEnvio(re.compile(r"Uploading (?P<caminho>.+)$"), None)
    assert d.linha("Uploading Perfil/Gabriel.md", 0) == "Perfil/Gabriel.md"
    assert d.linha("Downloading x.md", 0) is None


def test_modo_a_sem_grupo_usa_match_inteiro():
    d = DetectorEnvio(re.compile(r"PUSH \S+"), None)
    assert d.linha("xx PUSH a.md yy", 0) == "PUSH a.md"


def test_modo_b_mudanca_sem_download():
    r = mudancas_sem_download(["a.md", "b.md"], {"a.md": 95.0}, agora=100.0)
    assert r == ["b.md"]
    assert mudancas_sem_download(["a.md"], {"a.md": 10.0}, agora=500.0) == ["a.md"]  # fora da tolerância


# ---------- laço (Historico.passo) ----------

class AvisosFalso:
    def __init__(self):
        self.enviados = []
        self.reenvios = 0

    def enviar(self, g, t, d):
        self.enviados.append((g, t, d))

    def reenviar_fila(self):
        self.reenvios += 1
        return 0


@pytest.fixture
def amb(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    (tmp_path / "logs").mkdir()
    return v, tmp_path / "historico.git", tmp_path / "logs" / "sync.log", AvisosFalso()


def hist(amb, modo, envio=None, download=None, **kw):  # kw: tolerancia_s, posicao
    v, g, log, av = amb
    det = DetectorEnvio(re.compile(envio) if envio else None, re.compile(download) if download else None)
    return Historico(v, g, log, av, modo=modo, detector=det, **kw)


def test_modo_a_alerta_via_passo(amb):
    v, g, log, av = amb
    h = hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$")
    h.passo(0)  # log ainda não existe: tolerado
    log.write_text("Downloading x.md\nUploading Perfil/G.md\nUploading b.md\n")
    h.passo(30)
    assert av.reenvios == 2
    assert av.enviados == [("grave", "Alteração com origem no servidor", "Perfil/G.md\nb.md")]
    h.passo(60)
    assert len(av.enviados) == 1  # linhas já lidas não repetem


def test_log_linha_parcial_espera_o_fim(amb):
    v, g, log, av = amb
    h = hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$")
    log.write_text("Uploading a.md\nUploading b")
    h.passo(1)
    assert av.enviados[0][2] == "a.md"
    with open(log, "a") as f:
        f.write(".md\n")
    h.passo(2)
    assert av.enviados[1][2] == "b.md"


def test_log_truncado_e_substituido(amb):
    v, g, log, av = amb
    h = hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$")
    log.write_text("Uploading aaaaaaaaaaaaaaaa.md\n")
    h.passo(1)
    log.write_text("Uploading b.md\n")  # truncou: menor que o offset
    h.passo(2)
    assert av.enviados[-1][2] == "b.md"
    log.unlink()
    log.write_text("Uploading cccccccccccccccccccccccccc.md\n")  # substituído (inode novo)
    h.passo(3)
    assert av.enviados[-1][2] == "cccccccccccccccccccccccccc.md"
    assert len(av.enviados) == 3


def test_log_bytes_invalidos(amb):
    v, g, log, av = amb
    h = hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$")
    log.write_bytes(b"Uploading \xff.md\n")
    h.passo(1)
    assert len(av.enviados) == 1


def test_modo_b_ignora_primeiro_commit_e_obsidian(amb):
    v, g, log, av = amb
    (v / "a.md").write_text("a")
    h = hist(amb, "B", download=r"Downloading (?P<caminho>.+)$", tolerancia_s=120)
    h.passo(0)  # importação inicial: nunca alerta
    h.passo(500)
    assert av.enviados == []
    (v / ".obsidian").mkdir()
    (v / ".obsidian" / "workspace.json").write_text("{}")
    h.passo(530)
    h.passo(700)
    assert av.enviados == []  # .obsidian/ é ignorado no alerta
    (v / "b.md").write_text("b")
    (v / "c.md").write_text("c")
    h.passo(730)
    log.write_text("Downloading c.md\n")
    h.passo(760)
    h.passo(900)  # passou a tolerância desde a mudança
    assert av.enviados == [("grave", "Alteração com origem no servidor", "b.md")]
    h.passo(2000)
    assert len(av.enviados) == 1


def test_modo_b_download_antes_do_commit(amb):
    v, g, log, av = amb
    h = hist(amb, "B", download=r"Downloading (?P<caminho>.+)$", tolerancia_s=120)
    h.passo(0)
    log.write_text("Downloading n.md\n")
    (v / "n.md").write_text("n")
    h.passo(30)
    h.passo(1000)
    assert av.enviados == []


def test_detalhes_limitados_a_200(amb):
    v, g, log, av = amb
    h = hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$")
    log.write_text("".join(f"Uploading f{i}.md\n" for i in range(250)))
    h.passo(1)
    linhas = av.enviados[0][2].split("\n")
    assert len(linhas) == 201 and linhas[-1] == "… e mais 50"


def test_sem_deteccao_commita_e_avisa_uma_vez(amb, capsys):
    v, g, log, av = amb
    (v / "a.md").write_text("a")
    h = Historico(v, g, log, av, modo=None, detector=None)
    h.iniciar()
    h.iniciar()
    h.passo(0)
    log.write_text("Uploading x.md\n")
    (v / "b.md").write_text("b")
    h.passo(30)
    assert av.enviados == [("normal", "Detecção de envio não configurada", av.enviados[0][2])]
    assert "detecção" in capsys.readouterr().err.lower()
    assert git(g, v, "rev-list", "--count", "HEAD").strip() == "2"


def test_excecao_no_passo_nao_derruba(amb, capsys):
    v, g, log, av = amb
    h = hist(amb, "A", envio=r"x")
    def quebra(agora):
        raise RuntimeError("boom")
    h.passo = quebra
    h.passo_seguro(0)  # não levanta
    assert "historico" in capsys.readouterr().err


def test_ler_deteccao(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    assert ler_deteccao(tmp_path) is None  # ausente
    (cfg / "avisos.json").write_text("{ruim")
    assert ler_deteccao(tmp_path) is None
    (cfg / "avisos.json").write_text(json.dumps({"url": "http://x", "tokens": {"gateway": "a", "historico": "b"}}))
    assert ler_deteccao(tmp_path) is None
    (cfg / "avisos.json").write_text(json.dumps({"deteccao": {"modo": "A", "envio": "(["}}))
    assert ler_deteccao(tmp_path) is None  # regex inválida
    (cfg / "avisos.json").write_text(json.dumps({"deteccao": {"modo": "A"}}))
    assert ler_deteccao(tmp_path) is None  # sem envio
    (cfg / "avisos.json").write_text(json.dumps({"deteccao": {"modo": "B", "envio": "x", "download": "d (?P<caminho>.+)"}}))
    modo, det = ler_deteccao(tmp_path)
    assert modo == "B" and isinstance(det, DetectorEnvio)
    (cfg / "avisos.json").write_text(json.dumps({"deteccao": {"modo": "A", "envio": "u (?P<caminho>.+)"}}))
    assert ler_deteccao(tmp_path)[0] == "A"


def test_log_ilegivel_nao_impede_commit(amb, capsys):
    v, g, log, av = amb
    log.mkdir()  # sync.log é um diretório
    (v / "a.md").write_text("a")
    h = hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$")
    h.passo(0)  # não levanta
    assert git(g, v, "rev-list", "--count", "HEAD").strip() == "1"
    assert "sync.log" in capsys.readouterr().err
    assert av.enviados == []


def test_log_sem_permissao_nao_impede_commit(amb):
    import os
    if os.geteuid() == 0:
        pytest.skip("root ignora permissões")
    v, g, log, av = amb
    log.write_text("Uploading x.md\n")
    log.chmod(0)
    (v / "a.md").write_text("a")
    h = hist(amb, "B", download=r"Downloading (?P<caminho>.+)$")
    h.passo(0)
    log.chmod(0o644)
    assert git(g, v, "rev-list", "--count", "HEAD").strip() == "1"


def test_retoma_posicao_apos_reinicio(amb, tmp_path):
    v, g, log, av = amb
    pos = tmp_path / "logs" / "historico-posicao.json"
    h1 = hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$", posicao=pos)
    log.write_text("Uploading a.md\n")
    h1.passo(1)
    assert pos.exists() and len(av.enviados) == 1
    h2 = hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$", posicao=pos)  # "reinício"
    h2.passo(2)
    assert len(av.enviados) == 1  # nada repetido
    with open(log, "a") as f:
        f.write("Uploading b.md\n")
    h2.passo(3)
    assert av.enviados[-1][2] == "b.md" and len(av.enviados) == 2


def test_log_rotacionado_apos_reinicio_le_do_zero(amb, tmp_path):
    v, g, log, av = amb
    pos = tmp_path / "logs" / "historico-posicao.json"
    h1 = hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$", posicao=pos)
    log.write_text("Uploading aaaaaaaa.md\n")
    h1.passo(1)
    log.unlink()
    log.write_text("Uploading zzzzzzzzzzzzzzzz.md\nUploading y.md\n")  # outro conteúdo, maior
    h2 = hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$", posicao=pos)
    h2.passo(2)
    assert av.enviados[-1][2] == "zzzzzzzzzzzzzzzz.md\ny.md"


def test_posicao_corrompida_le_do_zero(amb, tmp_path):
    v, g, log, av = amb
    pos = tmp_path / "logs" / "historico-posicao.json"
    pos.parent.mkdir(exist_ok=True)
    pos.write_text("{lixo")
    log.write_text("Uploading a.md\n")
    hist(amb, "A", envio=r"Uploading (?P<caminho>.+)$", posicao=pos).passo(1)
    assert len(av.enviados) == 1


def test_grave_real_fica_na_fila_do_historico_com_alertas_fora(amb, tmp_path):
    """Avisos real (fila própria do histórico): o grave fica no disco se o alertas cair."""
    import httpx
    from vault_gateway.avisos import Avisos

    def fora(req):
        raise httpx.ConnectError("fora", request=req)

    v, g, log, _ = amb
    fila = tmp_path / "fila-avisos" / "historico"
    av = Avisos("http://alertas.teste", "TH", fila, cliente=httpx.Client(transport=httpx.MockTransport(fora)))
    h = Historico(v, g, log, av, modo="A",
                  detector=DetectorEnvio(re.compile(r"Uploading (?P<caminho>.+)$"), None))
    log.write_text("Uploading a.md\n")
    h.passo(1)
    arquivos = list(fila.glob("*.json"))
    assert len(arquivos) == 1
    assert json.loads(arquivos[0].read_text())["gravidade"] == "grave"
