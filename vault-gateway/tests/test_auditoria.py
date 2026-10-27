import json

import pytest

from vault_gateway.auditoria import MOTIVOS, registrar


def test_registro_negado_tem_motivo(tmp_path):
    r = registrar(tmp_path / "a.jsonl", cliente="claude", ferramenta="ler", alvo="../x", resultado="negada", motivo="fora_do_vault")
    linha = json.loads((tmp_path / "a.jsonl").read_text().splitlines()[-1])
    assert linha["cliente"] == "claude" and linha["motivo"] == "fora_do_vault"
    assert r == linha and linha["ts"]


def test_cliente_none_vira_desconhecido_e_cria_pasta(tmp_path):
    log = tmp_path / "logs" / "novo" / "a.jsonl"
    r = registrar(log, cliente=None, ferramenta="listar", alvo="", resultado="negada", motivo="token_ausente")
    assert r["cliente"] == "desconhecido" and log.exists()


def test_permitida_e_acumula_linhas_e_unicode(tmp_path):
    log = tmp_path / "a.jsonl"
    registrar(log, cliente="c", ferramenta="ler", alvo="Referências/Nota.md", resultado="permitida", motivo=None)
    registrar(log, cliente="c", ferramenta="ler", alvo="b", resultado="permitida", motivo=None)
    texto = log.read_text()
    assert len(texto.splitlines()) == 2 and "Referências" in texto


def test_alvo_truncado_em_500(tmp_path):
    r = registrar(tmp_path / "a.jsonl", cliente="c", ferramenta="buscar", alvo="x" * 900, resultado="permitida", motivo=None)
    assert len(r["alvo"]) == 500


def test_validacoes(tmp_path):
    log = tmp_path / "a.jsonl"
    with pytest.raises(ValueError):
        registrar(log, cliente="c", ferramenta="ler", alvo="a", resultado="talvez", motivo=None)
    with pytest.raises(ValueError):
        registrar(log, cliente="c", ferramenta="ler", alvo="a", resultado="negada", motivo="inventado")
    with pytest.raises(ValueError):
        registrar(log, cliente="c", ferramenta="ler", alvo="a", resultado="negada", motivo=None)
    assert not log.exists()
    assert MOTIVOS == {"token_ausente", "token_invalido", "fora_do_vault", "excluido", "ferramenta_desconhecida"}
