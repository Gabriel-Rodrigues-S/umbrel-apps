#!/usr/bin/env python3
"""Coletor da Inbox do Chat (PC).

Copia, via ssh (só comandos de leitura), as notas novas que o Chat criou na
pasta de espera do servidor para `<vault do PC>/Inbox/`. O servidor é tratado
como não confiável: nomes e conteúdos são revalidados aqui, nada é
sobrescrito, apagado ou gravado fora de `Inbox/`. Só biblioteca padrão.
"""
import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 102_400
MAX_POR_EXECUCAO = 20
MAX_SUFIXO = 99
MAX_NOME = 100
TIMEOUT_LISTA = 120
TIMEOUT_BAIXA = 60

_PERMITIDOS = set(" -_.()")
_HEX = set("0123456789abcdef")


class SshIndisponivel(Exception):
    """O servidor não respondeu ao ssh (conexão, timeout ou ssh ausente)."""


class RemotoFalhou(Exception):
    """O ssh conectou, mas o comando remoto falhou."""

    def __init__(self, codigo: int):
        super().__init__(f"comando remoto falhou (código {codigo})")
        self.codigo = codigo


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _chave(nome: str) -> str:
    return _nfc(nome).casefold()


def _log(msg: str) -> None:
    print(f"coleta-inbox: {msg}", flush=True)


def _erro(msg: str) -> None:
    print(f"coleta-inbox: {msg}", file=sys.stderr, flush=True)


def nome_valido(nome: str) -> str | None:
    """Mesmas regras do gateway (validar_nome). Devolve o nome em NFC ou None."""
    if not isinstance(nome, str):
        return None
    nome = _nfc(nome)
    if any(c in "/\\" or ord(c) < 32 or ord(c) == 127 for c in nome):
        return None
    if (
        not nome.endswith(".md")
        or not 1 <= len(nome) <= MAX_NOME
        or nome[0] in ". "
        or nome[:-3].endswith(" ")
        or ".." in nome
        or not all(c.isalnum() or c in _PERMITIDOS for c in nome)
    ):
        return None
    return nome


def _ssh(ssh_host: str, comando: str, timeout: int, runner) -> bytes:
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", ssh_host, comando]
    try:
        p = runner(argv, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise SshIndisponivel("ssh excedeu o tempo limite") from e
    except OSError as e:
        raise SshIndisponivel(f"não foi possível executar ssh: {e}") from e
    if p.returncode == 255:
        raise SshIndisponivel("ssh não conseguiu conectar (código 255)")
    if p.returncode != 0:
        raise RemotoFalhou(p.returncode)
    return p.stdout or b""


def _parse_lista(saida: bytes) -> dict[str, str]:
    # sha256sum -z: "<64 hex><espaço><espaço ou *><nome>\0", sem escape no nome
    r: dict[str, str] = {}
    for rec in saida.split(b"\0"):
        if len(rec) < 67 or rec[64:65] != b" " or rec[65:66] not in (b" ", b"*"):
            continue
        try:
            h = rec[:64].decode("ascii").lower()
            nome = rec[66:].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not set(h) <= _HEX:
            continue
        if nome.startswith("./"):
            nome = nome[2:]
        r[nome] = h
    return r


def listar_remoto(ssh_host: str, caminho_remoto: str, runner=subprocess.run) -> dict[str, str]:
    cmd = (
        f"cd -- {shlex.quote(caminho_remoto)} && "
        "find . -maxdepth 1 -type f ! -name '.*' -print0 | xargs -0 -r sha256sum -z"
    )
    return _parse_lista(_ssh(ssh_host, cmd, TIMEOUT_LISTA, runner))


def baixar(ssh_host: str, caminho_remoto: str, nome: str, runner=subprocess.run) -> bytes:
    """Até MAX_BYTES+1 bytes (o byte a mais denuncia arquivo grande demais)."""
    alvo = caminho_remoto.rstrip("/") + "/" + nome
    return _ssh(ssh_host, f"head -c {MAX_BYTES + 1} -- {shlex.quote(alvo)}", TIMEOUT_BAIXA, runner)


def _conteudo_ok(dados: bytes) -> bool:
    if not dados or len(dados) > MAX_BYTES or b"\0" in dados:
        return False
    try:
        dados.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def gravar_exclusivo(inbox: Path, nome: str, dados: bytes) -> str:
    """Cria o arquivo só se não existir (casefold + NFC); com colisão usa
    `-2`, `-3`... Devolve o nome gravado. Levanta OSError se `inbox` for
    link simbólico ou não der para gravar."""
    dfd = os.open(inbox, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        existentes = {_chave(n) for n in os.listdir(dfd)}
        base = nome[:-3]
        candidatos = [nome] + [f"{base}-{i}.md" for i in range(2, MAX_SUFIXO + 1)]
        for cand in candidatos:
            if _chave(cand) in existentes:
                continue
            try:
                fd = os.open(
                    cand,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o644,
                    dir_fd=dfd,
                )
            except FileExistsError:
                continue
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(dados)
                    f.flush()
                    os.fsync(f.fileno())
            except BaseException:
                try:  # só o arquivo que acabamos de criar
                    os.unlink(cand, dir_fd=dfd)
                except OSError:
                    pass
                raise
            return cand
        raise FileExistsError("sem nome livre")
    finally:
        os.close(dfd)


def _ler_estado(estado: Path) -> list[dict]:
    """Ausente = vazio. Existente mas inválido = ValueError (não arrisca duplicar)."""
    try:
        texto = Path(estado).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    dados = json.loads(texto)
    lista = dados.get("coletados") if isinstance(dados, dict) else None
    if not isinstance(lista, list) or not all(
        isinstance(e, dict) and isinstance(e.get("nome"), str) and isinstance(e.get("sha256"), str)
        for e in lista
    ):
        raise ValueError("estado inválido")
    return lista


def _gravar_estado(estado: Path, entradas: list[dict]) -> None:
    estado = Path(estado)
    estado.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=estado.parent, prefix=".estado-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"coletados": entradas}, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, estado)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def coletar(cfg: dict, estado: Path, runner=subprocess.run) -> int:
    """Copia as notas novas; devolve quantas gravou. SshIndisponivel e
    RemotoFalhou (na listagem) sobem sem tocar o estado."""
    ssh_host, remoto = cfg["ssh_host"], cfg["caminho_remoto"]
    vault = Path(cfg["caminho_local"]).expanduser()
    entradas = _ler_estado(estado)
    listado = listar_remoto(ssh_host, remoto, runner)

    # a listagem deu certo: esquece o que sumiu do servidor
    atuais = [e for e in entradas if e["nome"] in listado]
    if len(atuais) != len(entradas):
        _gravar_estado(estado, atuais)
    entradas = atuais
    ja = {e["nome"]: e["sha256"] for e in entradas}

    inbox = vault / "Inbox"
    try:
        st = os.lstat(inbox)
    except FileNotFoundError:
        st = None
    if st is not None and (stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode)):
        _erro("Inbox não é uma pasta comum (link ou arquivo); nada gravado")
        return 0

    gravadas = 0
    for nome in sorted(listado):
        if gravadas >= MAX_POR_EXECUCAO:
            break
        sha = listado[nome]
        if ja.get(nome) == sha:
            continue
        valido = nome_valido(nome)
        if valido is None:
            _erro(f"nome ignorado (inválido): {nome!r}")
            continue
        try:
            dados = baixar(ssh_host, remoto, nome, runner)
        except RemotoFalhou:
            _erro(f"download falhou, ignorado: {nome!r}")
            continue
        if hashlib.sha256(dados).hexdigest() != sha:
            _erro(f"sha256 diferente do listado, ignorado: {nome!r}")
            continue
        if not _conteudo_ok(dados):
            _erro(f"conteúdo inválido, ignorado: {nome!r}")
            continue
        try:
            if st is None:
                inbox.mkdir(exist_ok=True)
                st = os.lstat(inbox)
            gravado = gravar_exclusivo(inbox, valido, dados)
        except OSError as e:
            _erro(f"não foi possível gravar {nome!r}: {type(e).__name__}")
            continue
        _log(f"nota gravada: {gravado!r}")
        gravadas += 1
        entradas = [e for e in entradas if e["nome"] != nome]
        entradas.append({
            "nome": nome, "sha256": sha, "gravado": gravado,
            "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        ja[nome] = sha
        _gravar_estado(estado, entradas)  # já a cada nota: não duplica se cair no meio
    return gravadas


def main(config_dir: Path | None = None, estado: Path | None = None, runner=subprocess.run) -> int:
    config_dir = Path(config_dir or Path.home() / ".config" / "coleta-inbox")
    estado = Path(estado or Path.home() / ".local/state/coleta-inbox/coletados.json")
    try:
        cfg = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        for k in ("ssh_host", "caminho_remoto", "caminho_local"):
            if not isinstance(cfg[k], str) or not cfg[k]:
                raise TypeError(k)
    except (OSError, ValueError, KeyError, TypeError) as e:
        _erro(f"configuração ausente ou inválida ({type(e).__name__})")
        return 1
    try:
        coletar(cfg, estado, runner)
    except SshIndisponivel as e:
        _erro(f"servidor inacessível, nada feito: {e}")
        return 0
    except RemotoFalhou as e:
        _erro(str(e))
        return 1
    except (OSError, ValueError) as e:
        _erro(f"erro local ({type(e).__name__})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
