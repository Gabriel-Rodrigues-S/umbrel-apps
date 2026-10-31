"""Regras da Inbox: criar só notas novas na pasta de espera, sem sobrescrever."""
import json
import os
import tempfile
import threading
import time
import unicodedata
from pathlib import Path

MAX_BYTES = 102_400
MAX_POR_DIA = 5
JANELA_S = 86_400
RETENCAO_S = 30 * 86_400
MAX_NOME = 100

_PERMITIDOS = set(" -_.()")


class InboxNegada(Exception):
    """Negada; motivo: fora_da_inbox, nome_invalido, ja_existe, limite,
    sem_permissao ou conteudo_invalido."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _chave(nome: str) -> str:
    # mesmo nome para o iPhone e o Sync: NFC e caixa ignorada
    return _nfc(nome).casefold()


def validar_nome(nome: str) -> str:
    """Devolve o nome em NFC ou levanta InboxNegada."""
    if not isinstance(nome, str):
        raise InboxNegada("nome_invalido")
    nome = _nfc(nome)
    if any(c in "/\\" or ord(c) < 32 or ord(c) == 127 for c in nome):
        raise InboxNegada("fora_da_inbox")
    if (
        not nome.endswith(".md")
        or not 1 <= len(nome) <= MAX_NOME
        or nome[0] in ". "
        or nome[:-3].endswith(" ")
        or ".." in nome
        or len(nome.encode("utf-8", "surrogatepass")) > 255  # limite do sistema de arquivos
        or not all(c.isalnum() or c in _PERMITIDOS for c in nome)
    ):
        raise InboxNegada("nome_invalido")
    return nome


def validar_conteudo(conteudo: str) -> bytes:
    """Texto UTF-8 não vazio, sem NUL, até MAX_BYTES; devolve os bytes."""
    if not isinstance(conteudo, str) or not conteudo or "\x00" in conteudo:
        raise InboxNegada("conteudo_invalido")
    try:
        dados = conteudo.encode("utf-8")
    except UnicodeEncodeError:
        raise InboxNegada("conteudo_invalido") from None
    if len(dados) > MAX_BYTES:
        raise InboxNegada("conteudo_invalido")
    return dados


def clientes_permitidos(arquivo: Path) -> frozenset[str]:
    """Lê {"clientes": [...]}. Qualquer problema nega todos (falha fechada)."""
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # UnicodeDecodeError e JSONDecodeError são ValueError
        return frozenset()
    if not isinstance(dados, dict):
        return frozenset()
    lista = dados.get("clientes")
    if not isinstance(lista, list) or not lista or not all(isinstance(c, str) for c in lista):
        return frozenset()
    return frozenset(lista)


def _nomes(pasta: Path) -> set[str]:
    """Chaves dos nomes na pasta; erro de leitura conta como pasta vazia."""
    try:
        with os.scandir(pasta) as it:
            return {_chave(e.name) for e in it}
    except OSError:
        return set()


class Inbox:
    def __init__(self, espera: Path, vault: Path, config: Path):
        self.espera = Path(espera)
        self.vault = Path(vault)
        self.config = Path(config)
        self._trava = threading.Lock()
        self._garantir_pastas()

    def _garantir_pastas(self) -> None:
        (self.espera / ".parcial").mkdir(parents=True, exist_ok=True)

    def _recentes(self, agora: float) -> int:
        n = 0
        with os.scandir(self.espera) as it:
            for e in it:
                if e.name.startswith(".") or not e.is_file(follow_symlinks=False):
                    continue
                if e.stat(follow_symlinks=False).st_mtime > agora - JANELA_S:
                    n += 1
        return n

    def criar(self, cliente: str, nome: str, conteudo: str, agora: float | None = None) -> tuple[str, int]:
        """Grava a nota nova; devolve (nome gravado, bytes). Nunca sobrescreve."""
        agora = time.time() if agora is None else agora
        if cliente not in clientes_permitidos(self.config):
            raise InboxNegada("sem_permissao")
        nome = validar_nome(nome)
        dados = validar_conteudo(conteudo)

        self._garantir_pastas()
        fd, tmp = tempfile.mkstemp(dir=self.espera / ".parcial")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(dados)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o644)
            final = self.espera / nome
            with self._trava:
                if _chave(nome) in _nomes(self.espera) | _nomes(self.vault / "Inbox"):
                    raise InboxNegada("ja_existe")
                if self._recentes(agora) >= MAX_POR_DIA:
                    raise InboxNegada("limite")
                try:
                    os.link(tmp, final)  # atômico: nunca sobrescreve
                except FileExistsError:
                    raise InboxNegada("ja_existe") from None
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return nome, len(dados)

    def limpar(self, agora: float | None = None) -> int:
        """Apaga notas com mais de RETENCAO_S; devolve quantas. Ignora pastas e links."""
        agora = time.time() if agora is None else agora
        apagadas = 0
        try:
            with os.scandir(self.espera) as it:
                itens = list(it)
        except OSError:
            return 0
        for e in itens:
            try:
                if e.name.startswith(".") or not e.is_file(follow_symlinks=False):
                    continue
                if e.stat(follow_symlinks=False).st_mtime < agora - RETENCAO_S:
                    os.unlink(e.path)
                    apagadas += 1
            except OSError:
                continue
        return apagadas
