import os
import unicodedata

import pytest

from vault_gateway.caminhos import Negado
from vault_gateway.ferramentas import (
    NaoEncontrado, NaoLegivel, buscar, listar, ler, recentes,
)


def test_listar_esconde_excluidos(vault):
    nomes = [i["nome"] for i in listar(vault)]
    assert ".obsidian" not in nomes and "a.pdf" not in nomes and "Referências" in nomes
    assert nomes == sorted(nomes)


def test_listar_esconde_links_para_fora(vault):
    nomes = [i["nome"] for i in listar(vault)]
    assert "link-para-fora" not in nomes and "link-arquivo-fora.md" not in nomes
    assert "atalho-obsidian.json" not in nomes and "atalho.md" in nomes


def test_listar_tipos(vault):
    itens = {i["nome"]: i["tipo"] for i in listar(vault)}
    assert itens["Pasta"] == "pasta" and itens["atalho.md"] == "arquivo"


def test_listar_subpasta_com_acento(vault):
    assert listar(vault, "Referências") == [{"nome": "Nota com acento.md", "tipo": "arquivo"}]
    nfd = unicodedata.normalize("NFD", "Referências")
    assert len(listar(vault, nfd)) == 1


def test_listar_arquivo_ou_inexistente(vault):
    with pytest.raises(NaoEncontrado):
        listar(vault, "Pasta/b.txt")
    with pytest.raises(NaoEncontrado):
        listar(vault, "nao-existe")


def test_listar_excluida_e_fora_negadas(vault):
    with pytest.raises(Negado):
        listar(vault, ".obsidian")
    with pytest.raises(Negado):
        listar(vault, "link-para-fora")


def test_ler_ok_e_nfd(vault):
    assert "corpo" in ler(vault, "Referências/Nota com acento.md")
    nfd = unicodedata.normalize("NFD", "Referências/Nota com acento.md")
    assert "corpo" in ler(vault, nfd)


def test_ler_inexistente(vault):
    with pytest.raises(NaoEncontrado):
        ler(vault, "nao-existe.md")


def test_ler_pasta_e_nao_encontrado(vault):
    with pytest.raises(NaoEncontrado):
        ler(vault, "Pasta")


def test_ler_negados(vault):
    for rel in ("../fora.md", "link-arquivo-fora.md", ".obsidian/x.json", "a.pdf"):
        with pytest.raises(Negado):
            ler(vault, rel)


def test_ler_grande_e_invalida_sem_vazar_caminho(vault):
    (vault / "grande.md").write_text("nota " * 600_000)
    (vault / "ruim.md").write_bytes(b"\xff\xfe\x00nota")
    for rel in ("grande.md", "ruim.md"):
        with pytest.raises(NaoLegivel) as e:
            ler(vault, rel)
        assert str(vault) not in str(e.value) and rel in str(e.value)


def test_buscar_sem_diferenciar_maiusculas_e_com_trecho(vault):
    r = buscar(vault, "NOTA")
    assert r and all(len(x["trecho"]) <= 200 for x in r)


def test_buscar_trecho_centrado_em_texto_longo(vault):
    (vault / "longo.md").write_text("x" * 1000 + " AGULHA " + "y" * 1000)
    r = [x for x in buscar(vault, "agulha") if x["caminho"] == "longo.md"]
    assert len(r) == 1 and "AGULHA" in r[0]["trecho"] and len(r[0]["trecho"]) <= 200


def test_buscar_pula_arquivo_invalido_e_grande(vault):
    (vault / "ruim.md").write_bytes(b"\xff\xfe\x00nota")
    (vault / "grande.md").write_text("nota " * 600_000)   # > 2 MB
    caminhos = [x["caminho"] for x in buscar(vault, "nota")]
    assert "ruim.md" not in caminhos and "grande.md" not in caminhos


def test_buscar_respeita_limite(vault):
    assert len(buscar(vault, "a", limite=3)) <= 3


def test_buscar_vazio(vault):
    assert buscar(vault, "") == [] and buscar(vault, "   ") == []


def test_buscar_nao_le_fora_nem_excluidos(vault):
    for termo in ("segredo", "fora", "core"):
        assert buscar(vault, termo) == []
    assert buscar(vault, "{}") == []   # .obsidian/x.json e atalho-obsidian.json


def test_buscar_caminho_relativo_nfc_com_barra(vault):
    nfd = unicodedata.normalize("NFD", "Nota nfd.md")
    (vault / "Referências" / nfd).write_text("conteudo unico")
    r = buscar(vault, "unico")
    assert r[0]["caminho"] == "Referências/Nota nfd.md"
    assert unicodedata.is_normalized("NFC", r[0]["caminho"])


def test_buscar_ignora_extensao_binaria(vault):
    (vault / "a.pdf").write_text("nota")
    assert "a.pdf" not in [x["caminho"] for x in buscar(vault, "nota")]


def test_recentes_ordem_decrescente(vault):
    r = recentes(vault, 5)
    assert [x["modificado"] for x in r] == sorted((x["modificado"] for x in r), reverse=True)


def test_recentes_mais_novo_primeiro_n_e_iso(vault):
    antigo = vault / "Pasta" / "b.txt"
    novo = vault / "novo.md"
    novo.write_text("x")
    os.utime(antigo, (1_000_000_000, 1_000_000_000))
    os.utime(novo, (2_000_000_000, 2_000_000_000))
    r = recentes(vault, 1)
    assert [x["caminho"] for x in r] == ["novo.md"]
    assert r[0]["modificado"].endswith(("Z",)) or "+" in r[0]["modificado"] or "-" in r[0]["modificado"][10:]
    assert recentes(vault, 0) == []


def test_recentes_so_visiveis(vault):
    caminhos = [x["caminho"] for x in recentes(vault, 100)]
    assert not any(c.startswith((".obsidian", ".git", "link-")) for c in caminhos)
    assert "a.pdf" not in caminhos and "atalho-obsidian.json" not in caminhos
    assert "Referências/Nota com acento.md" in caminhos
