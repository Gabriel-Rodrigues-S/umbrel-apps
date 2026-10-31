"""Log de acesso em JSONL (uma linha por chamada), com rotação por tamanho."""
import json
import os
from datetime import datetime
from pathlib import Path

MOTIVOS = {"token_ausente", "token_invalido", "fora_do_vault", "excluido", "ferramenta_desconhecida",
           "fora_da_inbox", "nome_invalido", "ja_existe", "limite", "sem_permissao",
           "conteudo_invalido", "argumentos_invalidos"}
RESULTADOS = {"permitida", "negada"}
MAX_ALVO = 500
MAX_BYTES = 50 * 1024 * 1024  # 50 MB por arquivo
COPIAS = 5  # acesso.jsonl.1 … .5; a mais antiga é descartada


def _rotacionar(log: Path, copias: int) -> None:
    """acesso.jsonl → .1, .1 → .2 … ; a .<copias> some. Chamar sob a trava do log."""
    for n in range(copias - 1, 0, -1):
        origem = log.with_name(f"{log.name}.{n}")
        if origem.exists():
            os.replace(origem, log.with_name(f"{log.name}.{n + 1}"))
    os.replace(log, log.with_name(f"{log.name}.1"))


def registrar(log: Path, *, cliente: str | None, ferramenta: str, alvo: str,
              resultado: str, motivo: str | None, max_bytes: int = MAX_BYTES,
              copias: int = COPIAS, bytes_: int | None = None) -> dict:
    """Acrescenta uma linha; se passar de max_bytes, rotaciona antes. Não é seguro entre
    processos: o servidor chama sob a própria trava (um worker só)."""
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
    if bytes_ is not None:
        registro["bytes"] = bytes_
    linha = (json.dumps(registro, ensure_ascii=False) + "\n").encode("utf-8", "replace")
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        tamanho = log.stat().st_size
    except FileNotFoundError:
        tamanho = 0
    if tamanho and tamanho + len(linha) > max_bytes:
        _rotacionar(log, copias)
    with log.open("ab") as f:
        f.write(linha)
    return registro
