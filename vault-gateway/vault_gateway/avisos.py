"""Cliente do app de alertas, com fila em disco.

Fila primeiro: todo aviso é gravado (arquivo atômico) antes de qualquer tentativa
de rede; um único drenador por processo posta e apaga. Assim um aviso grave não se
perde se o processo morrer enquanto o app de alertas não responde.
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

TIMEOUT_S = 3
GRAVIDADES = ("grave", "normal", "info")
REMETENTES = ("gateway", "historico")
# limites do app de alertas (alertas/alertas/main.py: NovoAlerta e LIMITE_CORPO)
MAX_TITULO = 120
MAX_DETALHES = 19000  # folga sob os 20000 aceitos
MAX_CORPO = 60 * 1024  # folga sob os 64 KiB aceitos
MARCA_CORTE = "… (cortado)"
MAX_FILA = 5000
# respostas que valem nova tentativa; outro 4xx = recusa definitiva
REPETIR = {401, 403, 408, 429}


def _txt(valor) -> str:
    """str sem surrogates (não quebram o UTF-8)."""
    s = valor if isinstance(valor, str) else str(valor)
    return s.encode("utf-8", "replace").decode("utf-8")


def _cortar(s: str, limite: int) -> str:
    if len(s) <= limite:
        return s
    return s[:max(0, limite - len(MARCA_CORTE))] + MARCA_CORTE


def limitar(gravidade, titulo, detalhes) -> dict:
    """Corpo dentro dos limites do app de alertas (título, detalhes e tamanho em bytes)."""
    titulo = _cortar(_txt(titulo), MAX_TITULO) or "(sem título)"
    detalhes = _cortar(_txt(detalhes), MAX_DETALHES)
    corpo = {"gravidade": _txt(gravidade), "titulo": titulo, "detalhes": detalhes}
    while len(corpo_json(corpo)) > MAX_CORPO and corpo["detalhes"]:
        # caracteres que viram vários bytes (acentos, \u escapes): reduz em proporção
        excesso = len(corpo_json(corpo)) / MAX_CORPO
        novo = int(len(corpo["detalhes"]) / excesso * 0.95) - 1
        corpo["detalhes"] = _cortar(corpo["detalhes"], max(len(MARCA_CORTE), novo))
        if novo <= len(MARCA_CORTE):
            corpo["detalhes"] = MARCA_CORTE
            break
    return corpo


def corpo_json(corpo: dict) -> bytes:
    """Bytes exatos enviados ao app de alertas."""
    return json.dumps(corpo, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _erro(msg: str) -> None:
    print(f"avisos: {msg}", file=sys.stderr, flush=True)


class Avisos:
    def __init__(self, url: str, token: str, fila: Path, *, cliente: httpx.Client | None = None,
                 max_fila: int = MAX_FILA):
        self._url = url
        self._token = token
        self._fila = Path(fila)
        self._max_fila = max_fila
        self._cliente = cliente or httpx.Client(timeout=TIMEOUT_S)

    def _postar(self, corpo: dict) -> str:
        """'ok' (2xx), 'recusado' (4xx definitivo) ou 'depois'. Nunca expõe o token."""
        if not (self._url and self._token):
            return "depois"  # modo só fila
        try:
            r = self._cliente.post(
                self._url,
                content=corpo_json(limitar(corpo["gravidade"], corpo["titulo"], corpo["detalhes"])),
                headers={"Authorization": f"Bearer {self._token}",
                         "Content-Type": "application/json"},
                timeout=TIMEOUT_S,
            )
        except Exception:
            return "depois"
        if 200 <= r.status_code < 300:
            return "ok"
        if 400 <= r.status_code < 500 and r.status_code not in REPETIR:
            return "recusado"
        return "depois"

    def _pendentes(self) -> list[Path]:
        return sorted(p for p in self._fila.glob("*.json") if p.is_file())

    def guardar(self, gravidade: str, titulo: str, detalhes: str) -> bool:
        """Grava um arquivo por aviso (atômico, ordenável por tempo). Rápido, sem rede."""
        try:
            corpo = limitar(gravidade, titulo, detalhes)
            self._fila.mkdir(parents=True, exist_ok=True)
            if corpo["gravidade"] != "grave" and len(self._pendentes()) >= self._max_fila:
                _erro(f"fila cheia: aviso {corpo['gravidade']} descartado")
                return False
            nome = f"{time.time_ns()}-{uuid.uuid4().hex}.json"
            tmp = self._fila / f".{nome}.tmp"
            dado = {**corpo, "criado_em": datetime.now().astimezone().isoformat()}
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(json.dumps(dado, ensure_ascii=False))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._fila / nome)
            return True
        except Exception:
            _erro("aviso perdido: falha ao gravar a fila")
            return False

    def enviar(self, gravidade: str, titulo: str, detalhes: str) -> None:
        """Grava e drena na hora (para processos com um só laço, como o histórico)."""
        try:
            self.guardar(gravidade, titulo, detalhes)
            self.reenviar_fila()
        except Exception:
            _erro("erro inesperado ao enviar")

    def reenviar_fila(self) -> int:
        """Posta do mais antigo ao mais novo e apaga após 2xx.

        Recusa definitiva (4xx) → invalidos/ e segue; falha temporária → para.
        """
        enviados = 0
        try:
            arquivos = self._pendentes()
        except Exception:
            return 0
        for arq in arquivos:
            try:
                dado = json.loads(arq.read_text(encoding="utf-8"))
                corpo = {k: str(dado[k]) for k in ("gravidade", "titulo", "detalhes")}
                if corpo["gravidade"] not in GRAVIDADES:
                    raise ValueError
            except FileNotFoundError:
                continue
            except Exception:
                self._isolar(arq, "arquivo inválido")
                continue
            res = self._postar(corpo)
            if res == "depois":
                break
            if res == "recusado":
                self._isolar(arq, "recusado pelo app de alertas")
                continue
            try:
                arq.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                break  # não apagou: parar evita duplicar em loop
            enviados += 1
        return enviados

    def _isolar(self, arq: Path, motivo: str) -> None:
        try:
            destino = self._fila / "invalidos"
            destino.mkdir(exist_ok=True)
            os.replace(arq, destino / arq.name)
            _erro(f"{motivo}: {arq.name} movido para invalidos/")
        except Exception:
            _erro("arquivo da fila não pôde ser isolado")


def avisos_de_config(dados: Path, remetente: str | None = None) -> Avisos:
    """config/avisos.json → {"url", "tokens": {"gateway", "historico"}, "deteccao"}.

    O token é escolhido por REMETENTE (env); ausente, desconhecido ou config ruim →
    só fila (nunca usa o token do outro serviço). Fila própria: fila-avisos/<remetente>.
    """
    remetente = os.environ.get("REMETENTE", "") if remetente is None else remetente
    if remetente not in REMETENTES:
        _erro("REMETENTE ausente ou desconhecido: avisos ficam só na fila")
        return Avisos("", "", Path(dados) / "fila-avisos" / "sem-remetente")
    fila = Path(dados) / "fila-avisos" / remetente
    try:
        cfg = json.loads((Path(dados) / "config/avisos.json").read_text(encoding="utf-8"))
        url, token = cfg["url"], cfg["tokens"][remetente]
        if not (isinstance(url, str) and url.startswith(("http://", "https://"))
                and isinstance(token, str) and token):
            raise ValueError
    except Exception:
        _erro("config/avisos.json ausente ou inválido: avisos ficam na fila")
        url, token = "", ""
    return Avisos(url, token, fila)
