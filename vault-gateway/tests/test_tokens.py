import json
import os
import stat
import time

import pytest

from vault_gateway.tokens import Tokens, criar, main, revogar


def test_criar_e_reconhecer(tmp_path):
    arq = tmp_path / "tokens.json"
    t = criar(arq, "claude")
    assert Tokens(arq).cliente_do(t) == "claude" and t not in arq.read_text()


def test_revogar_sem_reiniciar(tmp_path):
    arq = tmp_path / "tokens.json"
    a = criar(arq, "claude")
    b = criar(arq, "teste")
    tk = Tokens(arq)
    assert tk.cliente_do(b) == "teste"
    revogar(arq, "teste")
    os.utime(arq, (time.time() + 2,) * 2)
    assert tk.cliente_do(b) is None and tk.cliente_do(a) == "claude"


@pytest.mark.parametrize("conteudo", [None, "", "{quebrado", "[]", '{"a": 1}', '{"a": null}'])
def test_arquivo_ruim_nega_tudo(tmp_path, conteudo):
    arq = tmp_path / "tokens.json"
    if conteudo is not None:
        arq.write_text(conteudo)
    assert Tokens(arq).cliente_do("qualquer") is None


def test_arquivo_estraga_depois_nega_tudo(tmp_path):
    arq = tmp_path / "tokens.json"
    t = criar(arq, "claude")
    tk = Tokens(arq)
    assert tk.cliente_do(t) == "claude"
    arq.write_text("{quebrado")
    os.utime(arq, (time.time() + 2,) * 2)
    assert tk.cliente_do(t) is None


def test_arquivo_apagado_nega_tudo(tmp_path):
    arq = tmp_path / "tokens.json"
    t = criar(arq, "claude")
    tk = Tokens(arq)
    assert tk.cliente_do(t) == "claude"
    arq.unlink()
    assert tk.cliente_do(t) is None


@pytest.mark.parametrize("token", [None, "", "errado"])
def test_token_vazio_ou_errado(tmp_path, token):
    arq = tmp_path / "tokens.json"
    criar(arq, "claude")
    assert Tokens(arq).cliente_do(token) is None


def test_grava_so_hash_com_modo_0600(tmp_path):
    arq = tmp_path / "sub" / "tokens.json"
    criar(arq, "claude")
    assert stat.S_IMODE(arq.stat().st_mode) == 0o600
    dados = json.loads(arq.read_text())
    assert list(dados) == ["claude"] and len(dados["claude"]) == 64
    assert [p.name for p in arq.parent.iterdir()] == ["tokens.json"]


def test_criar_nome_repetido_recusa(tmp_path):
    arq = tmp_path / "tokens.json"
    t = criar(arq, "claude")
    with pytest.raises(ValueError):
        criar(arq, "claude")
    assert Tokens(arq).cliente_do(t) == "claude"


@pytest.mark.parametrize("nome", ["", "A", "-x", "_x", "a b", "a/b", "é", "a" * 33])
def test_criar_nome_invalido(tmp_path, nome):
    with pytest.raises(ValueError):
        criar(tmp_path / "tokens.json", nome)


def test_criar_em_arquivo_corrompido_nao_sobrescreve(tmp_path):
    arq = tmp_path / "tokens.json"
    arq.write_text("{quebrado")
    with pytest.raises(ValueError):
        criar(arq, "claude")
    assert arq.read_text() == "{quebrado"


def test_revogar_inexistente(tmp_path):
    arq = tmp_path / "tokens.json"
    criar(arq, "claude")
    with pytest.raises(ValueError):
        revogar(arq, "outro")
    with pytest.raises(ValueError):
        revogar(tmp_path / "nao-existe.json", "claude")


def test_cli_criar_listar_revogar(tmp_path, monkeypatch, capsys):
    arq = tmp_path / "tokens.json"
    monkeypatch.setenv("TOKENS_ARQUIVO", str(arq))
    assert main(["criar", "claude"]) == 0
    saida = capsys.readouterr()
    token = saida.out.strip()
    assert saida.err == "" and Tokens(arq).cliente_do(token) == "claude"
    assert main(["listar"]) == 0
    out = capsys.readouterr().out
    assert out == "claude\n" and token not in out
    assert main(["revogar", "claude"]) == 0
    assert capsys.readouterr().out == ""
    assert Tokens(arq).cliente_do(token) is None


@pytest.mark.parametrize(
    "argv", [[], ["criar"], ["criar", "A!"], ["revogar", "nao-existe"], ["xpto"], ["listar", "x"]]
)
def test_cli_uso_ruim_sai_com_2(tmp_path, monkeypatch, capsys, argv):
    monkeypatch.setenv("TOKENS_ARQUIVO", str(tmp_path / "tokens.json"))
    assert main(argv) == 2
    saida = capsys.readouterr()
    assert saida.out == "" and saida.err.strip()


def test_cli_modulo_real(tmp_path):
    import subprocess
    import sys

    env = {**os.environ, "TOKENS_ARQUIVO": str(tmp_path / "t.json")}
    r = subprocess.run(
        [sys.executable, "-m", "vault_gateway.tokens", "criar", "x"],
        capture_output=True, text=True, env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert r.returncode == 0 and len(r.stdout.strip()) >= 40
