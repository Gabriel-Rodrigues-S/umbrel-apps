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


# --- rotação por tamanho ---

def _reg(log, n, **kw):
    for i in range(n):
        registrar(log, cliente="c", ferramenta="ler", alvo=f"a{i:04d}", resultado="permitida",
                  motivo=None, **kw)


def test_rotacao_por_tamanho_mantem_5_copias(tmp_path):
    log = tmp_path / "acesso.jsonl"
    _reg(log, 1)
    linha = log.stat().st_size
    log.unlink()
    # 2 linhas por arquivo; 20 linhas → atual + 5 cópias (o resto é descartado)
    _reg(log, 20, max_bytes=2 * linha, copias=5)
    nomes = sorted(p.name for p in tmp_path.iterdir())
    assert nomes == ["acesso.jsonl"] + [f"acesso.jsonl.{n}" for n in range(1, 6)]
    for p in tmp_path.iterdir():
        assert p.stat().st_size <= 2 * linha
        for l in p.read_text().splitlines():
            json.loads(l)  # nenhuma linha partida
    # ordem: atual tem as mais novas; .5 as mais antigas mantidas
    alvo = lambda p: [json.loads(l)["alvo"] for l in p.read_text().splitlines()]
    assert alvo(log) == ["a0018", "a0019"]
    assert alvo(tmp_path / "acesso.jsonl.1") == ["a0016", "a0017"]
    assert alvo(tmp_path / "acesso.jsonl.5") == ["a0008", "a0009"]


def test_sem_rotacao_abaixo_do_limite(tmp_path):
    log = tmp_path / "acesso.jsonl"
    _reg(log, 10)
    assert [p.name for p in tmp_path.iterdir()] == ["acesso.jsonl"]


def test_linha_maior_que_o_limite_vai_para_arquivo_novo(tmp_path):
    log = tmp_path / "acesso.jsonl"
    _reg(log, 3, max_bytes=10)
    # cada linha fica sozinha num arquivo; nunca rotaciona arquivo vazio
    assert len(log.read_text().splitlines()) == 1
    assert len((tmp_path / "acesso.jsonl.1").read_text().splitlines()) == 1


def test_rotacao_segura_sob_trava_com_threads(tmp_path):
    import threading

    log = tmp_path / "acesso.jsonl"
    trava = threading.Lock()

    def trabalho(k):
        for i in range(50):
            with trava:
                registrar(log, cliente="c", ferramenta="ler", alvo=f"{k}-{i}", resultado="permitida",
                          motivo=None, max_bytes=2000, copias=100)

    ts = [threading.Thread(target=trabalho, args=(k,)) for k in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    linhas = [json.loads(l) for p in tmp_path.iterdir() for l in p.read_text().splitlines()]
    assert len(linhas) == 200
