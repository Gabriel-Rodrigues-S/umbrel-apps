#!/usr/bin/env python3
"""Conferência PC x Umbrel (camada 4).

Compara os SHA-256 do vault no PC com a cópia no servidor (via ssh, só
leitura). Se a MESMA divergência persistir em 2 execuções seguidas, envia um
aviso "normal" ao app de alertas. Só biblioteca padrão.
"""
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request
from pathlib import Path

PASTAS_IGNORADAS = (".obsidian", ".git", ".trash")
TITULO_FALHA = "Conferência do vault falhou"
INTERVALO_FALHA = 24 * 3600
TITULO = "Cópias do vault divergentes"
LIMITE_DETALHES = 200
TIMEOUT_SSH = 300
TIMEOUT_POST = 10


class SshIndisponivel(Exception):
    """O servidor não respondeu ao ssh (conexão, timeout ou ssh ausente)."""


class RemotoFalhou(Exception):
    """O ssh conectou, mas o comando remoto falhou (caminho errado, find etc.)."""

    def __init__(self, codigo: int, stderr: str = ""):
        super().__init__(f"comando remoto falhou (código {codigo})")
        self.codigo = codigo
        self.stderr = stderr


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def somas_locais(vault: Path) -> dict[str, str]:
    vault = Path(vault)
    r: dict[str, str] = {}
    for raiz, pastas, arquivos in os.walk(vault, followlinks=False):
        pastas[:] = [p for p in pastas if p not in PASTAS_IGNORADAS]
        for nome in arquivos:
            caminho = Path(raiz) / nome
            if caminho.is_symlink():
                continue
            rel = caminho.relative_to(vault).as_posix()
            try:
                r[_nfc(rel)] = _sha256_arquivo(caminho)
            except OSError as e:
                print(f"ilegível, ignorado: {rel} ({e.strerror})", file=sys.stderr)
    return r


def _desescapar(nome: str) -> str:
    out, i = [], 0
    while i < len(nome):
        c = nome[i]
        if c == "\\" and i + 1 < len(nome):
            seg = nome[i + 1]
            if seg == "\\":
                out.append("\\")
            elif seg == "n":
                out.append("\n")
            elif seg == "r":
                out.append("\r")
            else:
                out.append(c + seg)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_sha256sum(saida: str) -> dict[str, str]:
    r: dict[str, str] = {}
    for linha in saida.split("\n"):
        escapado = linha.startswith("\\")
        if escapado:
            linha = linha[1:]
        if len(linha) < 67 or linha[64:66] != "  ":
            continue
        h, nome = linha[:64], linha[66:]
        try:
            int(h, 16)
        except ValueError:
            continue
        if escapado:
            nome = _desescapar(nome)
        if nome.startswith("./"):
            nome = nome[2:]
        r[_nfc(nome)] = h.lower()
    return r


def _comando_remoto(caminho_remoto: str) -> str:
    excl = " ".join(
        f"-not -path './{p}/*' -not -path '*/{p}/*'" for p in PASTAS_IGNORADAS
    )
    return (
        f"cd {shlex.quote(caminho_remoto)} && "
        f"find . -type f {excl} -exec sha256sum {{}} +"
    )


def somas_remotas(ssh_host: str, caminho_remoto: str, runner=subprocess.run) -> dict[str, str]:
    argv = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "--", ssh_host, _comando_remoto(caminho_remoto),
    ]
    try:
        p = runner(argv, capture_output=True, text=True, timeout=TIMEOUT_SSH)
    except subprocess.TimeoutExpired as e:
        raise SshIndisponivel("ssh excedeu o tempo limite") from e
    except OSError as e:
        raise SshIndisponivel(f"não foi possível executar ssh: {e}") from e
    if p.returncode == 255:
        raise SshIndisponivel("ssh não conseguiu conectar (código 255)")
    if p.returncode != 0:
        raise RemotoFalhou(p.returncode, (p.stderr or "")[:300])
    return parse_sha256sum(p.stdout)


def diferencas(a: dict[str, str], b: dict[str, str]) -> list[str]:
    return sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))


def _ler_estado(estado: Path) -> dict:
    try:
        dados = json.loads(Path(estado).read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            return dados
    except (OSError, ValueError):
        pass
    return {}


def _lista(dados: dict, chave: str) -> set[str]:
    v = dados.get(chave)
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return set(v)
    return set()


def _gravar_estado(estado: Path, dados: dict) -> None:
    estado = Path(estado)
    estado.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=estado.parent, prefix=".estado-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, estado)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def decidir(diffs: list[str], estado: Path) -> bool:
    """True se a mesma divergência persiste em 2 execuções e ainda não foi
    alertada com sucesso (ver marcar_alertado)."""
    dados = _ler_estado(estado)
    anterior = _lista(dados, "anterior")
    alertado = _lista(dados, "alertado")
    atual = set(diffs)
    if atual != alertado:
        alertado = set()  # divergência sumiu ou mudou: pode alertar de novo
    dados["anterior"] = sorted(atual)
    dados["alertado"] = sorted(alertado)
    _gravar_estado(estado, dados)
    return bool(atual) and atual == anterior and atual != alertado


def marcar_alertado(diffs: list[str], estado: Path) -> None:
    """Chamar só depois de um POST bem-sucedido."""
    dados = _ler_estado(estado)
    dados["alertado"] = sorted(set(diffs))
    _gravar_estado(estado, dados)


def montar_corpo_falha(codigo: int) -> dict:
    return {"gravidade": "normal", "titulo": TITULO_FALHA,
            "detalhes": f"código de saída: {codigo}"}


def montar_corpo(diffs: list[str]) -> dict:
    linhas = list(diffs[:LIMITE_DETALHES])
    if len(diffs) > LIMITE_DETALHES:
        linhas.append(f"… e mais {len(diffs) - LIMITE_DETALHES}")
    return {"gravidade": "normal", "titulo": TITULO, "detalhes": "\n".join(linhas)}


def enviar_alerta(url: str, token: str, diffs: list[str], corpo: dict | None = None) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(corpo or montar_corpo(diffs), ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_POST) as resp:
        if not 200 <= resp.status < 300:
            raise OSError(f"HTTP {resp.status}")


def _erro(msg: str) -> None:
    print(f"conferencia-vault: {msg}", file=sys.stderr)


def main(config_dir=None, estado=None, vault=None,
         somas_remotas_fn=somas_remotas, enviar_fn=enviar_alerta, agora=time.time) -> int:
    config_dir = Path(config_dir or Path.home() / ".config" / "conferencia-vault")
    estado = Path(estado or Path.home() / ".local/state/conferencia-vault/estado.json")
    try:
        cfg = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        ssh_host = cfg["ssh_host"]
        caminho_remoto = cfg["caminho_remoto"]
        url = cfg["url_alertas"]
        caminho_local = Path(cfg["caminho_local"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        _erro(f"configuração ausente ou inválida ({type(e).__name__})")
        return 2
    token_path = config_dir / "token"
    try:
        if token_path.stat().st_mode & 0o077:
            _erro("arquivo do token acessível por grupo/outros; use chmod 600")
            return 2
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        _erro("arquivo do token ausente ou ilegível")
        return 2
    if not token:
        _erro("arquivo do token vazio")
        return 2

    locais = somas_locais(caminho_local)
    try:
        remotas = somas_remotas_fn(ssh_host, caminho_remoto)
    except SshIndisponivel as e:
        _erro(f"servidor inacessível, nada feito: {e}")
        return 0
    except RemotoFalhou as e:
        _erro(f"{e}; stderr: {e.stderr[:300]!r}")
        dados = _ler_estado(estado)
        t = agora()
        ultimo = dados.get("falha_alertada_em")
        if isinstance(ultimo, (int, float)) and 0 <= t - ultimo < INTERVALO_FALHA:
            return 0
        try:
            enviar_fn(url, token, [], montar_corpo_falha(e.codigo))
        except Exception as e2:
            _erro(f"falha ao enviar o aviso ({type(e2).__name__})")
            return 1
        dados["falha_alertada_em"] = t
        _gravar_estado(estado, dados)
        return 0

    diffs = diferencas(locais, remotas)
    if decidir(diffs, estado):
        try:
            enviar_fn(url, token, diffs)
        except Exception as e:  # nunca incluir o token na mensagem
            _erro(f"falha ao enviar o aviso ({type(e).__name__})")
            return 1
        marcar_alertado(diffs, estado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
