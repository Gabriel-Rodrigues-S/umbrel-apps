"""Resolução segura de caminhos dentro do vault (fronteira de segurança)."""
import os
import unicodedata
from pathlib import Path

EXTENSOES = {".md", ".html", ".txt", ".csv", ".json", ".py"}
PASTAS_EXCLUIDAS = {".obsidian", ".git", ".trash"}

_EXCLUIDAS_CF = {p.casefold() for p in PASTAS_EXCLUIDAS}


class Negado(Exception):
    """Acesso negado; motivo: 'fora_do_vault' ou 'excluido'."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _tem_pasta_excluida(partes) -> bool:
    # caixa ignorada: o vault pode vir de sistema de arquivos insensível
    return any(p.casefold() in _EXCLUIDAS_CF for p in partes)


def _ext_legivel(caminho: Path) -> bool:
    return caminho.suffix.lower() in EXTENSOES


def _achar(pasta: Path, nome: str) -> str:
    """Nome real em disco: tenta NFC, depois NFD, depois compara por NFC."""
    if os.path.lexists(pasta / nome):
        return nome
    nfd = unicodedata.normalize("NFD", nome)
    if os.path.lexists(pasta / nfd):
        return nfd
    try:
        with os.scandir(pasta) as it:
            for e in it:
                if _nfc(e.name) == nome:
                    return e.name
    except OSError:
        pass
    return nome


def resolver(raiz: Path, relativo: str, *, para_ler: bool) -> Path:
    raiz_r = Path(raiz).resolve()
    if "\x00" in relativo:
        raise Negado("fora_do_vault")
    rel = _nfc(relativo)
    if rel.startswith("/") or os.path.isabs(rel):
        raise Negado("fora_do_vault")
    partes = [p for p in rel.split("/") if p not in ("", ".")]
    # ".." nunca é aceito, nem quando ficaria dentro do vault
    if ".." in partes:
        raise Negado("fora_do_vault")

    # erros de sistema (nome longo, laço de links) viram Negado, sem vazar caminho
    try:
        atual = raiz_r
        for parte in partes:
            atual = atual / _achar(atual, parte)

        # links simbólicos resolvidos antes de checar o limite
        final = atual.resolve(strict=False)
        if not final.is_relative_to(raiz_r):
            raise Negado("fora_do_vault")

        # exclusão vale para o caminho pedido e para o destino real (links internos)
        partes_reais = final.relative_to(raiz_r).parts
        if _tem_pasta_excluida(partes) or _tem_pasta_excluida(partes_reais):
            raise Negado("excluido")

        eh_dir = final.is_dir()
        if not eh_dir and (para_ler or final.is_file()):
            pedido = Path(partes[-1]) if partes else final
            if not (_ext_legivel(pedido) and _ext_legivel(final)):
                raise Negado("excluido")
    except (OSError, RuntimeError):
        raise Negado("fora_do_vault") from None

    # fora do try: IsADirectoryError é deliberado (mensagem só com o caminho relativo)
    if eh_dir and para_ler:
        raise IsADirectoryError(relativo)
    return final


def visivel(raiz: Path, caminho: Path) -> bool:
    """False para fora do vault, pastas excluídas e arquivos de extensão não legível."""
    raiz_r = Path(raiz).resolve()
    try:
        real = Path(caminho).resolve(strict=False)
        if not real.is_relative_to(raiz_r):
            return False
        reais = real.relative_to(raiz_r).parts
        pedidas = Path(os.path.abspath(caminho)).relative_to(raiz_r).parts
        if _tem_pasta_excluida(reais) or _tem_pasta_excluida(pedidas):
            return False
        if real.is_file():
            return _ext_legivel(real) and _ext_legivel(Path(caminho))
        return True
    except (ValueError, OSError, RuntimeError):
        return False
