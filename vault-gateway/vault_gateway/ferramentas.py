"""Ferramentas de leitura do vault (funções puras, só leitura)."""
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .caminhos import _EXCLUIDAS_CF, Negado, resolver, visivel

LIMITE_BYTES = 2 * 1024 * 1024
TAMANHO_TRECHO = 200


class NaoEncontrado(Exception):
    """Caminho inexistente (ou pasta onde se esperava arquivo, e vice-versa)."""


class NaoLegivel(Exception):
    """Arquivo grande demais ou com codificação inválida; mensagem só com caminho relativo."""


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _ler_texto(real: Path, rel: str) -> str:
    """Lê UTF-8 de até 2 MB; erros viram NaoLegivel sem caminho absoluto."""
    try:
        with open(real, "rb") as f:
            dados = f.read(LIMITE_BYTES + 1)
        if len(dados) > LIMITE_BYTES:
            raise NaoLegivel(f"arquivo maior que 2 MB: {rel}")
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        raise NaoLegivel(f"codificação inválida: {rel}") from None
    except OSError:
        raise NaoLegivel(f"não foi possível ler: {rel}") from None


def listar(raiz, pasta: str = "") -> list[dict]:
    raiz = Path(raiz)
    real = resolver(raiz, pasta, para_ler=False)
    if not real.is_dir():
        raise NaoEncontrado(pasta)
    itens = []
    try:
        with os.scandir(real) as it:
            for e in it:
                p = real / e.name
                if not visivel(raiz, p):
                    continue
                itens.append({"nome": _nfc(e.name),
                              "tipo": "pasta" if p.is_dir() else "arquivo"})
    except OSError:
        raise NaoEncontrado(pasta) from None
    return sorted(itens, key=lambda i: i["nome"])


def ler(raiz, caminho: str) -> str:
    raiz = Path(raiz)
    try:
        real = resolver(raiz, caminho, para_ler=True)
    except IsADirectoryError:
        raise NaoEncontrado(caminho) from None
    if not real.is_file():
        raise NaoEncontrado(caminho)
    # abre o Path devolvido pelo resolver (não refaz raiz + relativo)
    return _ler_texto(real, caminho)


def _arquivos(raiz: Path):
    """Gera (relativo NFC com '/', caminho real) dos arquivos legíveis e visíveis."""
    raiz_r = raiz.resolve()
    for dirpath, dirnames, filenames in os.walk(raiz_r, followlinks=False):
        # poda pastas excluídas e ordena para resultado estável
        dirnames[:] = sorted(d for d in dirnames if d.casefold() not in _EXCLUIDAS_CF)
        for nome in sorted(filenames):
            p = Path(dirpath) / nome
            if not visivel(raiz_r, p):
                continue
            rel = _nfc(p.relative_to(raiz_r).as_posix())
            real = p
            if p.is_symlink():
                # link nunca pode levar para fora do vault
                try:
                    real = resolver(raiz_r, p.relative_to(raiz_r).as_posix(), para_ler=True)
                except (Negado, IsADirectoryError):
                    continue
            if real.is_file():
                yield rel, real


def _trecho(texto: str, inicio: int, fim: int) -> str:
    """Janela de até 200 caracteres centrada na ocorrência, espaços normalizados."""
    meio = (inicio + fim) // 2
    a = max(0, meio - TAMANHO_TRECHO // 2)
    janela = texto[a:a + TAMANHO_TRECHO]
    return " ".join(janela.split())[:TAMANHO_TRECHO]


def buscar(raiz, texto: str, limite: int = 50) -> list[dict]:
    raiz = Path(raiz)
    if not texto or not texto.strip() or limite <= 0:
        return []
    padrao = re.compile(re.escape(_nfc(texto.strip())), re.IGNORECASE)
    achados = []
    for rel, real in _arquivos(raiz):
        try:
            conteudo = _nfc(_ler_texto(real, rel))
        except NaoLegivel:
            continue  # grande, inválido ou ilegível: pula
        m = padrao.search(conteudo)
        if m:
            achados.append({"caminho": rel, "trecho": _trecho(conteudo, m.start(), m.end())})
            if len(achados) >= limite:
                break
    return achados


def recentes(raiz, n: int = 20) -> list[dict]:
    raiz = Path(raiz)
    if n <= 0:
        return []
    itens = []
    for rel, real in _arquivos(raiz):
        try:
            itens.append((real.stat().st_mtime, rel))
        except OSError:
            continue
    itens.sort(key=lambda t: (-t[0], t[1]))
    return [{"caminho": rel,
             "modificado": datetime.fromtimestamp(m).astimezone().isoformat()}
            for m, rel in itens[:n]]
