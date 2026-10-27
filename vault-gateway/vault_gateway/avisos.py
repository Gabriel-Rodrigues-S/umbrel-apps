"""Cliente do app de alertas, com fila em disco para reenvio."""
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

TIMEOUT_S = 3


class Avisos:
    def __init__(self, url: str, token: str, fila: Path, *, cliente: httpx.Client | None = None):
        self._url = url
        self._token = token
        self._fila = Path(fila)
        self._cliente = cliente or httpx.Client(timeout=TIMEOUT_S)

    def _postar(self, corpo: dict) -> bool:
        """True só com resposta 2xx. Qualquer erro vira False (sem detalhes, por causa do token)."""
        try:
            r = self._cliente.post(
                self._url,
                json={k: corpo[k] for k in ("gravidade", "titulo", "detalhes")},
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=TIMEOUT_S,
            )
            return 200 <= r.status_code < 300
        except Exception:
            return False

    def _guardar(self, gravidade: str, titulo: str, detalhes: str) -> None:
        """Grava um arquivo por aviso, de forma atômica; nomes ordenáveis por tempo."""
        try:
            self._fila.mkdir(parents=True, exist_ok=True)
            nome = f"{time.time_ns()}-{uuid.uuid4().hex}.json"
            tmp = self._fila / f".{nome}.tmp"
            dado = {"gravidade": gravidade, "titulo": titulo, "detalhes": detalhes,
                    "criado_em": datetime.now().astimezone().isoformat()}
            tmp.write_text(json.dumps(dado, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._fila / nome)
        except Exception:
            print("aviso perdido: falha ao gravar a fila", file=sys.stderr)

    def enviar(self, gravidade: str, titulo: str, detalhes: str) -> None:
        try:
            corpo = {"gravidade": gravidade, "titulo": titulo, "detalhes": detalhes}
            if not self._postar(corpo):
                self._guardar(gravidade, titulo, detalhes)
        except Exception:
            print("aviso perdido: erro inesperado ao enviar", file=sys.stderr)

    def reenviar_fila(self) -> int:
        """Reenvia do mais antigo ao mais novo; apaga após 2xx; para na primeira falha."""
        enviados = 0
        try:
            arquivos = sorted(p for p in self._fila.glob("*.json") if p.is_file())
        except Exception:
            return 0
        for arq in arquivos:
            try:
                dado = json.loads(arq.read_text(encoding="utf-8"))
                corpo = {k: str(dado[k]) for k in ("gravidade", "titulo", "detalhes")}
            except Exception:
                self._isolar(arq)
                continue
            if not self._postar(corpo):
                break
            try:
                arq.unlink()
            except Exception:
                break  # não apagou: parar evita duplicar em loop
            enviados += 1
        return enviados

    def _isolar(self, arq: Path) -> None:
        try:
            destino = self._fila / "invalidos"
            destino.mkdir(exist_ok=True)
            os.replace(arq, destino / arq.name)
        except Exception:
            print("aviso: arquivo inválido na fila não pôde ser isolado", file=sys.stderr)
