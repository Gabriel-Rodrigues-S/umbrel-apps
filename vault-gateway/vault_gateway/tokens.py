"""Tokens por cliente: só o SHA-256 fica em disco; revogar vale sem reiniciar."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
from pathlib import Path

PADRAO_HASH = re.compile(r"[0-9a-f]{64}")
PADRAO_NOME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
ARQUIVO_PADRAO = "/data/config/tokens.json"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ler(caminho: Path) -> dict[str, str]:
    """Lê e valida o arquivo. Qualquer problema levanta ValueError (falha fechada)."""
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # UnicodeDecodeError e JSONDecodeError são ValueError
        raise ValueError("arquivo de tokens ilegível") from e
    if not isinstance(dados, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and PADRAO_HASH.fullmatch(v)
        for k, v in dados.items()
    ):
        raise ValueError("arquivo de tokens malformado")
    return dados


def _gravar(caminho: Path, dados: dict[str, str]) -> None:
    """Grava de forma atômica (temp na mesma pasta + replace), modo 0600."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=caminho.parent, prefix=".tokens-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(dados, indent=2, sort_keys=True))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, caminho)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Tokens:
    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self._chave = None  # (mtime_ns, tamanho, inode) do último estado lido
        self._hashes: dict[str, str] = {}

    def _recarregar(self) -> None:
        try:
            st = os.stat(self.caminho)
        except OSError:
            self._chave, self._hashes = None, {}
            return
        chave = (st.st_mtime_ns, st.st_size, st.st_ino)
        if chave == self._chave:
            return
        try:
            self._hashes = _ler(self.caminho)
        except ValueError:
            self._hashes = {}  # arquivo ruim: nega tudo, não mantém o cache antigo
        self._chave = chave

    def cliente_do(self, token: str | None) -> str | None:
        self._recarregar()
        if not token or not isinstance(token, str):
            return None
        h = _hash(token)
        achado = None
        for nome, guardado in self._hashes.items():  # percorre todos, sem sair cedo
            if hmac.compare_digest(h, guardado) and achado is None:
                achado = nome
        return achado


def _validar_nome(nome: str) -> None:
    if not isinstance(nome, str) or not PADRAO_NOME.fullmatch(nome):
        raise ValueError("nome inválido (use a-z, 0-9, _ ou -, até 32 caracteres)")


def _ler_para_editar(caminho: Path) -> dict[str, str]:
    """Ausente = lista vazia; existente mas ruim = erro (nunca sobrescrever)."""
    if not Path(caminho).exists():
        return {}
    return _ler(caminho)


def criar(caminho: Path, nome: str) -> str:
    _validar_nome(nome)
    dados = _ler_para_editar(caminho)
    if nome in dados:
        raise ValueError(f"já existe um token para '{nome}'; revogue antes")
    token = secrets.token_urlsafe(32)
    dados[nome] = _hash(token)
    _gravar(caminho, dados)
    return token


def revogar(caminho: Path, nome: str) -> None:
    dados = _ler_para_editar(caminho)
    if nome not in dados:
        raise ValueError(f"não existe token para '{nome}'")
    del dados[nome]
    _gravar(caminho, dados)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    caminho = Path(os.environ.get("TOKENS_ARQUIVO", ARQUIVO_PADRAO))
    uso = "uso: python -m vault_gateway.tokens {criar|revogar} <nome> | listar"
    try:
        if len(argv) == 2 and argv[0] == "criar":
            print(criar(caminho, argv[1]))  # única saída que mostra o token
        elif len(argv) == 2 and argv[0] == "revogar":
            revogar(caminho, argv[1])
        elif len(argv) == 1 and argv[0] == "listar":
            for nome in sorted(_ler_para_editar(caminho)):
                print(nome)
        else:
            print(uso, file=sys.stderr)
            return 2
    except ValueError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
