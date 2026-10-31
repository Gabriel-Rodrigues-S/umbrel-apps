import json
import os
import stat
import threading
import unicodedata

import pytest

from vault_gateway.inbox import Inbox, InboxNegada, validar_nome

NOME = "Relatorio-Chat-Novembro-2026.md"


@pytest.fixture
def inbox(tmp_path, vault):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "inbox.json").write_text(json.dumps({"clientes": ["claude"]}))
    return Inbox(tmp_path / "espera", vault, cfg / "inbox.json")


def motivo(fn, *args):
    with pytest.raises(InboxNegada) as e:
        fn(*args)
    return e.value.motivo


def test_cria_arquivo_com_conteudo_exato(inbox):
    assert inbox.criar("claude", NOME, "# Oi\n") == (NOME, 5)
    arq = inbox.espera / NOME
    assert arq.read_bytes() == b"# Oi\n"
    assert stat.S_IMODE(arq.stat().st_mode) == 0o644
    assert list((inbox.espera / ".parcial").iterdir()) == []


@pytest.mark.parametrize("nome", ["../x.md", "Contexto/x.md", "a\\b.md", "x\x00.md", "x\n.md"])
def test_nome_com_pasta_fora_da_inbox(inbox, nome):
    assert motivo(inbox.criar, "claude", nome, "x") == "fora_da_inbox"


@pytest.mark.parametrize(
    "nome",
    ["x.txt", "x.MD", ".md", ".oculto.md", " x.md", "x .md", "a..b.md", "x*.md", "a" * 98 + ".md"],
)
def test_nome_invalido(inbox, nome):
    assert motivo(inbox.criar, "claude", nome, "x") == "nome_invalido"


def test_nome_acima_de_255_bytes_e_invalido(inbox):
    assert motivo(inbox.criar, "claude", "界" * 97 + ".md", "x") == "nome_invalido"


def test_nome_ascii_de_97_letras_continua_valido(inbox):
    nome = "a" * 97 + ".md"
    assert inbox.criar("claude", nome, "x")[0] == nome


def test_nome_no_limite_de_100_passa(inbox):
    nome = "a" * 97 + ".md"
    assert inbox.criar("claude", nome, "x")[0] == nome


def test_nome_aceita_acentos_e_parenteses(inbox):
    nome = "Relatório (nov) 2026_v2.md"
    assert inbox.criar("claude", nome, "x")[0] == nome


def test_nome_nfd_vira_nfc(inbox):
    nfc = "Ação.md"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfd != nfc
    assert validar_nome(nfd) == nfc
    assert inbox.criar("claude", nfd, "x")[0] == nfc
    nomes = [p.name for p in inbox.espera.iterdir() if not p.name.startswith(".")]
    assert nomes == [nfc]


@pytest.mark.parametrize("conteudo", ["", "a\x00b", "é" * 51_201])
def test_conteudo_invalido(inbox, conteudo):
    assert motivo(inbox.criar, "claude", NOME, conteudo) == "conteudo_invalido"


def test_conteudo_no_limite_passa(inbox):
    assert inbox.criar("claude", NOME, "a" * 102_400) == (NOME, 102_400)


def test_ja_existe_na_espera_e_no_vault(inbox, vault):
    inbox.criar("claude", NOME, "um")
    assert motivo(inbox.criar, "claude", NOME, "dois") == "ja_existe"
    # caixa diferente no radical
    assert motivo(inbox.criar, "claude", NOME.lower(), "dois") == "ja_existe"
    # extensão em maiúsculas nem passa pela regra de nome
    assert motivo(inbox.criar, "claude", "relatorio-chat-novembro-2026.MD", "x") == "nome_invalido"
    # nome já no vault
    (vault / "Inbox").mkdir()
    (vault / "Inbox" / "Existente.md").write_text("x")
    assert motivo(inbox.criar, "claude", "existente.md", "x") == "ja_existe"
    # NFD no disco × NFC pedido
    nfd = unicodedata.normalize("NFD", "Ação.md")
    (vault / "Inbox" / nfd).write_text("x")
    assert motivo(inbox.criar, "claude", "Ação.md", "x") == "ja_existe"


def test_ja_existe_nao_altera_original(inbox):
    inbox.criar("claude", NOME, "original")
    assert motivo(inbox.criar, "claude", NOME, "outro") == "ja_existe"
    assert (inbox.espera / NOME).read_text() == "original"
    assert list((inbox.espera / ".parcial").iterdir()) == []


def test_corrida_mesmo_nome(inbox):
    barreira = threading.Barrier(2)
    resultados = {}

    def tarefa(conteudo):
        barreira.wait()
        try:
            resultados[conteudo] = inbox.criar("claude", NOME, conteudo)
        except InboxNegada as e:
            resultados[conteudo] = e.motivo

    ts = [threading.Thread(target=tarefa, args=(c,)) for c in ("aaa", "bbb")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    vencedoras = [c for c, r in resultados.items() if isinstance(r, tuple)]
    assert len(vencedoras) == 1
    perdedora = ({"aaa", "bbb"} - set(vencedoras)).pop()
    assert resultados[perdedora] == "ja_existe"
    assert (inbox.espera / NOME).read_text() == vencedoras[0]


def test_limite_5_em_24h(inbox):
    for i in range(5):
        inbox.criar("claude", f"n{i}.md", "x")
    assert motivo(inbox.criar, "claude", "n5.md", "x") == "limite"
    antigo = os.stat(inbox.espera / "n0.md").st_mtime - 86_401
    for i in range(5):
        os.utime(inbox.espera / f"n{i}.md", (antigo, antigo))
    assert inbox.criar("claude", "n5.md", "x") == ("n5.md", 1)


def test_sem_permissao(inbox):
    assert motivo(inbox.criar, "mordomo", NOME, "x") == "sem_permissao"
    assert not (inbox.espera / NOME).exists()


@pytest.mark.parametrize(
    "conteudo",
    [None, "{", '{"clientes": "claude"}', '{"clientes": []}', '{"clientes": [1]}', "[]"],
)
def test_config_ruim_ninguem_escreve(tmp_path, vault, conteudo):
    cfg = tmp_path / "inbox.json"
    if conteudo is not None:
        cfg.write_text(conteudo)
    i = Inbox(tmp_path / "espera", vault, cfg)
    assert motivo(i.criar, "claude", NOME, "x") == "sem_permissao"


def test_config_relida_sem_reiniciar(inbox):
    inbox.criar("claude", "a.md", "x")
    inbox.config.write_text(json.dumps({"clientes": ["outro"]}))
    assert motivo(inbox.criar, "claude", "b.md", "x") == "sem_permissao"


def test_limpar_apaga_mais_de_30_dias(inbox, tmp_path):
    inbox.criar("claude", "velho.md", "x")
    inbox.criar("claude", "novo.md", "x")
    agora = os.stat(inbox.espera / "novo.md").st_mtime
    velho = agora - 31 * 86_400
    os.utime(inbox.espera / "velho.md", (velho, velho))
    # parcial antigo e link simbólico antigo ficam intactos
    parcial = inbox.espera / ".parcial" / "tmp"
    parcial.write_text("x")
    os.utime(parcial, (velho, velho))
    alvo = tmp_path / "alvo.md"
    alvo.write_text("x")
    os.utime(alvo, (velho, velho))
    (inbox.espera / "link.md").symlink_to(alvo)
    assert inbox.limpar(agora) == 1
    assert not (inbox.espera / "velho.md").exists()
    assert (inbox.espera / "novo.md").exists()
    assert parcial.exists() and alvo.exists()
    assert (inbox.espera / "link.md").is_symlink()


def test_espera_criada_se_nao_existe(tmp_path, vault):
    cfg = tmp_path / "inbox.json"
    cfg.write_text(json.dumps({"clientes": ["claude"]}))
    espera = tmp_path / "a" / "b" / "espera"
    i = Inbox(espera, vault, cfg)
    assert espera.is_dir()
    assert i.criar("claude", NOME, "x")[0] == NOME
