"""Log de acesso em JSONL (uma linha por chamada)."""
import json
from datetime import datetime
from pathlib import Path

MOTIVOS = {"token_ausente", "token_invalido", "fora_do_vault", "excluido", "ferramenta_desconhecida"}
RESULTADOS = {"permitida", "negada"}
MAX_ALVO = 500


def registrar(log: Path, *, cliente: str | None, ferramenta: str, alvo: str,
              resultado: str, motivo: str | None) -> dict:
    if resultado not in RESULTADOS:
        raise ValueError(f"resultado inválido: {resultado!r}")
    if resultado == "negada" and motivo not in MOTIVOS:
        raise ValueError(f"motivo inválido para negada: {motivo!r}")
    registro = {
        "ts": datetime.now().astimezone().isoformat(),
        "cliente": cliente or "desconhecido",
        "ferramenta": ferramenta,
        "alvo": (alvo or "")[:MAX_ALVO],
        "resultado": resultado,
        "motivo": motivo,
    }
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro
