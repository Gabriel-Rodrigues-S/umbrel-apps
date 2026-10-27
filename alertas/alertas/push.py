"""Web Push: chaves VAPID e envio do texto genérico (nunca conteúdo do alerta)."""
import base64
import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from . import banco

log = logging.getLogger("alertas.push")

TTL = 86400  # um dia: depois disso o aviso perde o sentido
TEMPO_LIMITE = 10
PADRAO_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_trava = threading.Lock()


def texto(gravidade: str) -> str | None:
    if gravidade == "grave":
        return "Novo alerta grave no servidor"
    if gravidade == "normal":
        return "Novo alerta no servidor"
    return None  # info nunca gera push


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _de_b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _gerar() -> dict:
    k = ec.generate_private_key(ec.SECP256R1())
    privada = k.private_numbers().private_value.to_bytes(32, "big")
    publica = k.public_key().public_bytes(serialization.Encoding.X962,
                                          serialization.PublicFormat.UncompressedPoint)
    return {"privada": _b64(privada), "publica": _b64(publica)}


def _validar(d) -> dict:
    try:
        if not isinstance(d, dict):
            raise ValueError
        priv, pub = _de_b64(d["privada"]), _de_b64(d["publica"])
        if len(priv) != 32 or len(pub) != 65 or pub[0] != 4:
            raise ValueError
        k = ec.derive_private_key(int.from_bytes(priv, "big"), ec.SECP256R1())
        if k.public_key().public_bytes(serialization.Encoding.X962,
                                       serialization.PublicFormat.UncompressedPoint) != pub:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ValueError("vapid.json malformado") from None
    return {"privada": d["privada"], "publica": d["publica"]}


def _gravar(caminho: Path, dados: dict) -> None:
    """Gravação atômica, modo 0600."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=caminho.parent, prefix=".vapid-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(dados))
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


def chaves(config: Path) -> dict:
    """Lê config/vapid.json; gera na primeira vez. Arquivo ruim levanta ValueError (não sobrescreve)."""
    arq = Path(config) / "vapid.json"
    with _trava:
        if arq.exists():
            try:
                d = json.loads(arq.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise ValueError("vapid.json ilegível") from None
            return _validar(d)
        d = _gerar()
        _gravar(arq, d)
        return d


def _enviar_um(sub: dict, mensagem: str, k: dict, host: str, webpush) -> None:
    from py_vapid import Vapid

    webpush(
        subscription_info=sub,
        data=mensagem,
        vapid_private_key=Vapid.from_raw(k["privada"].encode("ascii")),
        vapid_claims={"sub": f"https://{host}"},  # dicionário novo a cada envio (o pywebpush altera)
        ttl=TTL,
        timeout=TEMPO_LIMITE,
    )


def enviar_todos(con, gravidade: str, chaves: dict, *, host: str | None, webpush=None) -> int:
    """Envia o texto genérico para todas as inscrições. Nunca levanta; devolve quantos deram certo."""
    try:
        mensagem = texto(gravidade)
        if mensagem is None:
            return 0
        if not host or not isinstance(host, str) or not PADRAO_HOST.fullmatch(host):
            log.warning("push não enviado: 'host' ausente ou inválido em config/app.json")
            return 0
        if webpush is None:
            from pywebpush import webpush
        from pywebpush import WebPushException

        enviados = 0
        for sub in banco.inscricoes(con):
            try:
                _enviar_um(sub, mensagem, chaves, host, webpush)
                enviados += 1
            except WebPushException as e:
                st = e.status_code if hasattr(e, "status_code") else getattr(e.response, "status_code", None)
                if st in (404, 410):
                    banco.remover_inscricao(con, sub["endpoint"])
                    log.info("inscrição de push expirada removida")
                else:
                    log.warning("push recusado (status %s)", st)  # nunca o corpo nem o endpoint
            except Exception as e:  # rede etc.
                log.warning("push falhou (%s)", type(e).__name__)
        return enviados
    except Exception as e:
        log.warning("push falhou (%s)", type(e).__name__)
        return 0
