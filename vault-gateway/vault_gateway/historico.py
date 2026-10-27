"""Serviço histórico: commita o vault num git fora dele e detecta envio ao Sync.

Modo A: o sync.log tem uma linha de envio (regex `envio`, grupo `caminho`).
Modo B: o sync.log registra downloads (regex `download`); mudança no vault sem
download correspondente dentro da tolerância é tratada como envio do servidor.
No modo B, caminhos sob `.obsidian/` (workspace*.json muda o tempo todo) são
commitados mas nunca geram alerta. A primeira commit (importação inicial) também não.
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from .avisos import avisos_de_config

INTERVALO_S = 30
TOLERANCIA_S = 120
TIMEOUT_GIT_S = 120
MAX_LINHAS_DETALHE = 200
TITULO_GRAVE = "Alteração com origem no servidor"


def _erro(msg: str) -> None:
    print(f"historico: {msg}", file=sys.stderr, flush=True)


def _git(git_dir: Path, vault: Path, *args: str, ok=(0,)) -> subprocess.CompletedProcess:
    """Roda git sem shell; o vault é só leitura e de outro uid (safe.directory=*)."""
    cmd = ["git", "-c", "safe.directory=*", "-c", "core.quotepath=false",
           f"--git-dir={git_dir}", f"--work-tree={vault}", *args]
    r = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_GIT_S,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8"})
    if r.returncode not in ok:
        raise RuntimeError(f"git {args[0]} falhou ({r.returncode}): {r.stderr.decode(errors='replace')[:200]}")
    return r


def _iniciar_repo(vault: Path, git_dir: Path) -> None:
    git_dir.mkdir(parents=True, exist_ok=True)
    _git(git_dir, vault, "init", "-q", "-b", "main")
    _git(git_dir, vault, "config", "core.bare", "false")
    _git(git_dir, vault, "config", "user.name", "historico")
    _git(git_dir, vault, "config", "user.email", "historico@localhost")
    _git(git_dir, vault, "config", "commit.gpgsign", "false")
    _git(git_dir, vault, "config", "core.autocrlf", "false")


def _commitar(vault: Path, git_dir: Path) -> tuple[list[str], bool] | None:
    """None se nada mudou; senão (arquivos alterados, foi_o_primeiro_commit)."""
    vault, git_dir = Path(vault), Path(git_dir)
    if not (git_dir / "HEAD").exists():
        _iniciar_repo(vault, git_dir)
    _git(git_dir, vault, "add", "-A")
    r = _git(git_dir, vault, "diff", "--cached", "--name-only", "-z")
    alterados = [n.decode("utf-8", "replace") for n in r.stdout.split(b"\0") if n]
    if not alterados:
        return None
    inicial = _git(git_dir, vault, "rev-parse", "--verify", "-q", "HEAD", ok=(0, 1)).returncode != 0
    msg = "auto: " + datetime.now().astimezone().isoformat(timespec="seconds")
    _git(git_dir, vault, "commit", "-q", "-m", msg)
    return alterados, inicial


def commitar(vault: Path, git_dir: Path) -> bool:
    """add -A + commit se houver mudança (.obsidian/ entra). True se commitou."""
    return _commitar(vault, git_dir) is not None


class DetectorEnvio:
    def __init__(self, padrao_envio: re.Pattern | None, padrao_download: re.Pattern | None):
        self.padrao_envio = padrao_envio
        self.padrao_download = padrao_download
        self.downloads: dict[str, float] = {}  # caminho -> quando o download foi visto

    @staticmethod
    def _caminho(m: re.Match) -> str:
        return (m.groupdict().get("caminho") or m.group(0)).strip()

    def linha(self, texto: str, agora: float) -> str | None:
        """Envio (modo A) → caminho. Linha de download (modo B) é só registrada."""
        if self.padrao_download is not None:
            m = self.padrao_download.search(texto)
            if m:
                self.downloads[self._caminho(m)] = agora
                return None
        if self.padrao_envio is not None:
            m = self.padrao_envio.search(texto)
            if m:
                return self._caminho(m)
        return None


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def mudancas_sem_download(alterados: list[str], downloads_recentes: dict[str, float],
                          agora: float, tolerancia_s=TOLERANCIA_S) -> list[str]:
    """Alterados sem download registrado dentro da tolerância (compara em NFC)."""
    dl = {_nfc(k): v for k, v in downloads_recentes.items()}
    return [c for c in alterados
            if _nfc(c) not in dl or agora - dl[_nfc(c)] > tolerancia_s]


class _LeitorLog:
    """Lê só as linhas novas; reinicia se o arquivo encolheu ou foi trocado."""

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self.offset = 0
        self.inode = None
        self.inicio = b""

    def novas(self) -> list[str]:
        try:
            st = self.caminho.stat()
            with open(self.caminho, "rb") as f:
                # impressão digital: inode pode ser reaproveitado numa rotação
                inicio = f.read(64)
                trocado = (st.st_ino != self.inode or st.st_size < self.offset
                           or inicio[:len(self.inicio)] != self.inicio[:len(inicio)])
                if trocado:
                    self.offset = 0
                self.inode = st.st_ino
                self.inicio = inicio if (trocado or len(inicio) > len(self.inicio)) else self.inicio
                f.seek(self.offset)
                dados = f.read()
        except FileNotFoundError:
            return []
        fim = dados.rfind(b"\n")
        if fim < 0:
            return []  # linha incompleta (ou nada novo): espera o resto
        self.offset += fim + 1
        return [l.decode("utf-8", "replace").rstrip("\r") for l in dados[:fim].split(b"\n")]


def formatar_detalhes(caminhos: list[str]) -> str:
    unicos = list(dict.fromkeys(caminhos))
    linhas = unicos[:MAX_LINHAS_DETALHE]
    if len(unicos) > MAX_LINHAS_DETALHE:
        linhas.append(f"… e mais {len(unicos) - MAX_LINHAS_DETALHE}")
    return "\n".join(linhas)


class Historico:
    def __init__(self, vault: Path, git_dir: Path, log: Path, avisos, *, modo: str | None,
                 detector: DetectorEnvio | None, tolerancia_s: float = TOLERANCIA_S):
        self.vault, self.git_dir = Path(vault), Path(git_dir)
        self.avisos = avisos
        self.modo = modo if detector is not None else None
        self.detector = detector
        self.tolerancia_s = tolerancia_s
        self._leitor = _LeitorLog(log)
        self._pendentes: dict[str, float] = {}  # modo B: caminho -> quando mudou
        self._avisou_inicio = False

    def iniciar(self) -> None:
        """Sem detecção configurada: uma linha no stderr e um aviso normal (só uma vez)."""
        if self.modo is None and not self._avisou_inicio:
            self._avisou_inicio = True
            _erro("detecção de envio não configurada (config/avisos.json): só commits")
            self.avisos.enviar("normal", "Detecção de envio não configurada",
                               "config/avisos.json sem 'deteccao' válido: o histórico só commita.")

    def passo(self, agora: float) -> None:
        try:
            self.avisos.reenviar_fila()
        except Exception:
            _erro("falha ao reenviar a fila de avisos")
        caminhos: list[str] = []
        if self.detector is not None:
            for texto in self._leitor.novas():
                c = self.detector.linha(texto, agora)
                if c and self.modo == "A":
                    caminhos.append(c)
        try:
            res = _commitar(self.vault, self.git_dir)
        except Exception as e:
            _erro(f"falha ao commitar: {e}")
            res = None
        if self.modo == "B":
            if res and not res[1]:  # a importação inicial nunca alerta
                for c in res[0]:
                    if not c.startswith(".obsidian/"):
                        self._pendentes.setdefault(c, agora)
            caminhos += self._vencidos_modo_b(agora)
        if caminhos:
            self.avisos.enviar("grave", TITULO_GRAVE, formatar_detalhes(caminhos))

    def _vencidos_modo_b(self, agora: float) -> list[str]:
        """Espera a tolerância (o download pode aparecer no log depois do commit) e decide."""
        prontos = [c for c, t in self._pendentes.items() if agora - t >= self.tolerancia_s]
        suspeitos: list[str] = []
        for c in prontos:
            t = self._pendentes.pop(c)
            suspeitos += mudancas_sem_download([c], self.detector.downloads, t, self.tolerancia_s)
        # poda downloads antigos
        limite = agora - 10 * self.tolerancia_s
        self.detector.downloads = {k: v for k, v in self.detector.downloads.items() if v >= limite}
        return suspeitos

    def passo_seguro(self, agora: float) -> None:
        try:
            self.passo(agora)
        except Exception as e:
            _erro(f"erro no passo: {type(e).__name__}")


def ler_deteccao(dados: Path) -> tuple[str, DetectorEnvio] | None:
    """(modo, detector) a partir de config/avisos.json; None se ausente ou inválido."""
    try:
        d = json.loads((Path(dados) / "config/avisos.json").read_text(encoding="utf-8"))["deteccao"]
        modo = d["modo"]
        envio = re.compile(d["envio"]) if modo == "A" else None
        download = re.compile(d["download"]) if modo == "B" else None
        if modo not in ("A", "B"):
            return None
        return modo, DetectorEnvio(envio, download)
    except Exception:
        return None


def main() -> None:
    vault = Path(os.environ.get("VAULT_DIR", "/data/vault"))
    dados = Path(os.environ.get("DADOS_DIR", "/data"))
    det = ler_deteccao(dados)
    h = Historico(vault, dados / "historico.git", dados / "logs/sync.log", avisos_de_config(dados),
                  modo=det[0] if det else None, detector=det[1] if det else None)
    parar = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: parar.set())
    signal.signal(signal.SIGINT, lambda *_: parar.set())
    h.iniciar()
    import time
    while not parar.is_set():
        h.passo_seguro(time.time())
        parar.wait(INTERVALO_S)


if __name__ == "__main__":
    main()
