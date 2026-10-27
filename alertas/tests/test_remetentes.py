import hashlib
import json
import stat

import pytest

from alertas import remetentes
from alertas.remetentes import Remetentes, criar, main, revogar


def test_criar_so_nomes_aceitos(tmp_path):
    arq = tmp_path / "config/remetentes.json"
    for nome in ("gateway", "historico", "conferencia-pc"):
        assert criar(arq, nome)
    for nome in ("claude", "outro", "Gateway", "../x", ""):
        with pytest.raises(ValueError):
            criar(arq, nome)
    assert sorted(json.loads(arq.read_text())) == ["conferencia-pc", "gateway", "historico"]


def test_so_hash_em_disco_modo_600(tmp_path):
    arq = tmp_path / "r.json"
    t = criar(arq, "gateway")
    assert t not in arq.read_text()
    assert json.loads(arq.read_text())["gateway"] == hashlib.sha256(t.encode()).hexdigest()
    assert stat.S_IMODE(arq.stat().st_mode) == 0o600


def test_remetente_do_token(tmp_path):
    arq = tmp_path / "r.json"
    t = criar(arq, "historico")
    r = Remetentes(arq)
    assert r.remetente_do(t) == "historico"
    assert r.remetente_do("errado") is None
    assert r.remetente_do(None) is None
    assert r.remetente_do("") is None
    revogar(arq, "historico")
    assert r.remetente_do(t) is None


def test_falha_fechada(tmp_path):
    arq = tmp_path / "r.json"
    t = criar(arq, "gateway")
    r = Remetentes(arq)
    assert r.remetente_do(t) == "gateway"
    arq.write_text("{ruim")
    assert r.remetente_do(t) is None
    arq.write_text(json.dumps({"gateway": "nao-e-hash"}))
    assert r.remetente_do(t) is None
    arq.unlink()
    assert r.remetente_do(t) is None


def test_nome_fora_da_lista_editado_a_mao_nao_vale(tmp_path):
    arq = tmp_path / "r.json"
    arq.write_text(json.dumps({"intruso": hashlib.sha256(b"tok").hexdigest()}))
    assert Remetentes(arq).remetente_do("tok") is None


def test_arquivo_ruim_nunca_e_sobrescrito(tmp_path):
    arq = tmp_path / "r.json"
    arq.write_text("{ruim")
    with pytest.raises(ValueError):
        criar(arq, "gateway")
    assert arq.read_text() == "{ruim"


def test_cli(tmp_path, monkeypatch, capsys):
    arq = tmp_path / "r.json"
    monkeypatch.setenv("REMETENTES_ARQUIVO", str(arq))
    assert main(["criar", "gateway"]) == 0
    token = capsys.readouterr().out.strip()
    assert Remetentes(arq).remetente_do(token) == "gateway"
    assert main(["criar", "claude"]) == 2
    assert "erro" in capsys.readouterr().err
    assert main(["listar"]) == 0
    assert capsys.readouterr().out.split() == ["gateway"]
    assert main(["revogar", "gateway"]) == 0
    assert main(["revogar", "gateway"]) == 2
    assert main([]) == 2


def test_cli_arquivo_padrao_em_dados_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("REMETENTES_ARQUIVO", raising=False)
    monkeypatch.setenv("DADOS_DIR", str(tmp_path))
    assert main(["criar", "historico"]) == 0
    assert (tmp_path / "config/remetentes.json").exists()


def test_padrao_sem_env(monkeypatch):
    monkeypatch.delenv("REMETENTES_ARQUIVO", raising=False)
    monkeypatch.delenv("DADOS_DIR", raising=False)
    assert str(remetentes.arquivo_padrao()) == "/app/data/config/remetentes.json"
