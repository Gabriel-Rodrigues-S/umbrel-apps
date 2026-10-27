import unicodedata

import pytest

from vault_gateway.caminhos import EXTENSOES, PASTAS_EXCLUIDAS, Negado, resolver, visivel


def test_constantes():
    assert EXTENSOES == {".md", ".html", ".txt", ".csv", ".json", ".py"}
    assert PASTAS_EXCLUIDAS == {".obsidian", ".git", ".trash"}


@pytest.mark.parametrize("forma", ["NFC", "NFD"])
def test_resolve_nota_com_acento(vault, forma):
    rel = unicodedata.normalize(forma, "Referências/Nota com acento.md")
    p = resolver(vault, rel, para_ler=True)
    assert p.read_text().startswith("# Nota")


def test_arquivo_em_disco_nfd_pedido_em_nfc(vault):
    nfd = unicodedata.normalize("NFD", "Café.md")
    (vault / nfd).write_text("# Café")
    p = resolver(vault, unicodedata.normalize("NFC", "Café.md"), para_ler=True)
    assert p.read_text() == "# Café"


def test_pasta_em_disco_nfd(vault):
    nfd = unicodedata.normalize("NFD", "Ação")
    (vault / nfd).mkdir()
    (vault / nfd / "n.md").write_text("x")
    p = resolver(vault, "Ação/n.md", para_ler=True)
    assert p.read_text() == "x"


@pytest.mark.parametrize(
    "rel",
    [
        "../fora.md",
        "/etc/passwd",
        "a/../../x",
        "link-para-fora/segredo.md",
        "link-arquivo-fora.md",
        "Pasta/../../fora.md",
        "..",
        "a\x00b.md",
    ],
)
def test_fora_do_vault(vault, rel):
    with pytest.raises(Negado) as e:
        resolver(vault, rel, para_ler=True)
    assert e.value.motivo == "fora_do_vault"


def test_absoluto_dentro_do_vault_tambem_negado(vault):
    with pytest.raises(Negado) as e:
        resolver(vault, str(vault / "Pasta" / "b.txt"), para_ler=True)
    assert e.value.motivo == "fora_do_vault"


def test_fora_tem_precedencia_sobre_excluido(vault):
    with pytest.raises(Negado) as e:
        resolver(vault, "../fora/.git/x.md", para_ler=True)
    assert e.value.motivo == "fora_do_vault"


@pytest.mark.parametrize("rel", [".obsidian/x.json", ".git/config", "a.pdf", ".trash/n.md", "Pasta/.git/x.md"])
def test_excluido(vault, rel):
    with pytest.raises(Negado) as e:
        resolver(vault, rel, para_ler=True)
    assert e.value.motivo == "excluido"


@pytest.mark.parametrize("rel", [".Obsidian/x.json", ".GIT/config", "A.PDF", ".TRASH/n.md"])
def test_variacao_de_caixa_excluida(vault, rel):
    # decisão: exclusão ignora maiúsculas/minúsculas (vault pode vir de FS insensível)
    with pytest.raises(Negado) as e:
        resolver(vault, rel, para_ler=True)
    assert e.value.motivo == "excluido"


def test_extensao_maiuscula_legivel(vault):
    (vault / "N.MD").write_text("x")
    assert resolver(vault, "N.MD", para_ler=True).read_text() == "x"


def test_pasta_excluida_nao_listavel(vault):
    with pytest.raises(Negado) as e:
        resolver(vault, ".obsidian", para_ler=False)
    assert e.value.motivo == "excluido"


def test_link_interno_para_pasta_excluida(vault):
    with pytest.raises(Negado) as e:
        resolver(vault, "atalho-obsidian.json", para_ler=True)
    assert e.value.motivo == "excluido"


def test_pasta_comum_listavel(vault):
    assert resolver(vault, "Referências", para_ler=False).is_dir()


def test_raiz_listavel(vault):
    assert resolver(vault, "", para_ler=False) == vault.resolve()
    assert resolver(vault, ".", para_ler=False) == vault.resolve()


def test_pasta_para_ler_erro(vault):
    with pytest.raises(IsADirectoryError):
        resolver(vault, "Referências", para_ler=True)


def test_link_simbolico_interno_permitido(vault):
    p = resolver(vault, "atalho.md", para_ler=True)
    assert p.read_text().startswith("# Nota")


def test_inexistente_dentro_do_vault_retorna_caminho(vault):
    p = resolver(vault, "Pasta/nao-existe.md", para_ler=True)
    assert not p.exists()
    assert p.is_relative_to(vault.resolve())


def test_nfd_nao_vira_escape(vault):
    # nomes cuja normalização (NFC/NFD/NFKC) lembra ".." continuam sendo nomes comuns
    for nome in ["．．/fora.md", "..́/x.md", ".́./x.md", "‥/x.md"]:
        for forma in ("NFC", "NFD", "NFKC"):
            rel = unicodedata.normalize(forma, nome)
            try:
                p = resolver(vault, rel, para_ler=True)
            except Negado as e:
                assert e.motivo in {"fora_do_vault", "excluido"}
            else:
                assert p.is_relative_to(vault.resolve())


def test_nfkc_de_pontos_largos_vira_dotdot_e_negado(vault):
    # se o chamador normalizar em NFKC, ".." aparece e deve ser negado
    rel = unicodedata.normalize("NFKC", "．．/fora.md")
    assert rel == "../fora.md"
    with pytest.raises(Negado) as e:
        resolver(vault, rel, para_ler=True)
    assert e.value.motivo == "fora_do_vault"


# visivel
def test_visivel_arquivo_md(vault):
    assert visivel(vault, vault / "Referências" / "Nota com acento.md")


def test_visivel_pasta_comum(vault):
    assert visivel(vault, vault / "Referências")


@pytest.mark.parametrize("rel", [".obsidian", ".obsidian/x.json", ".git/config", "a.pdf"])
def test_nao_visivel(vault, rel):
    assert not visivel(vault, vault / rel)


def test_nao_visivel_fora(vault):
    assert not visivel(vault, vault.parent / "fora.md")
    assert not visivel(vault, vault / "link-arquivo-fora.md")
