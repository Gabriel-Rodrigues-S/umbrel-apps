"""
TTS Reader — Piper TTS backend (piper-tts 1.4.x API)
POST /synthesize  { text: str, speed: float }  → audio/wav
GET  /health                                    → { ready: bool, voice: str, error: str|None }
"""
from __future__ import annotations

import io
import traceback
import wave
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────
MODEL_DIR  = Path("/app/models")
MODEL_NAME = "pt_BR-faber-medium"
MODEL_PATH = MODEL_DIR / f"{MODEL_NAME}.onnx"

app = FastAPI()
_voice      = None
_load_error: Optional[str] = None


def _load_voice() -> None:
    global _voice, _load_error
    try:
        # piper-tts 1.4.x: PiperVoice lives in piper.voice
        from piper.voice import PiperVoice  # type: ignore
        print(f"[piper] loading model from {MODEL_PATH} …", flush=True)
        _voice = PiperVoice.load(str(MODEL_PATH))
        print(f"[piper] model loaded OK: {MODEL_PATH}", flush=True)
        _load_error = None
        _warmup()
    except Exception as exc:
        tb = traceback.format_exc()
        _load_error = f"{type(exc).__name__}: {exc}"
        print(f"[piper] load FAILED:\n{tb}", flush=True)
        _voice = None


def _warmup() -> None:
    """Synthesise a short phrase at startup to catch runtime issues early."""
    global _voice, _load_error
    try:
        from piper.config import SynthesisConfig  # type: ignore
        syn_config = SynthesisConfig(length_scale=1.0)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            _voice.synthesize_wav("teste", wf, syn_config=syn_config)
        buf.seek(0)
        n = len(buf.read())
        if n < 100:
            raise RuntimeError(
                f"warm-up produced only {n} bytes — espeak-ng data may be missing"
            )
        print(f"[piper] warm-up OK ({n} bytes)", flush=True)
    except Exception as exc:
        tb = traceback.format_exc()
        _load_error = f"warm-up failed — {type(exc).__name__}: {exc}"
        print(f"[piper] warm-up FAILED:\n{tb}", flush=True)
        _voice = None   # mark unavailable so /health reports correctly


_load_voice()


# ── Schema ────────────────────────────────────────────────────────────────
class SynthReq(BaseModel):
    text:  str
    speed: float = 1.0


# ── Endpoints ─────────────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    return {
        "ready": _voice is not None,
        "voice": MODEL_NAME,
        "error": _load_error,
    }


@app.post("/synthesize")
def synthesize(req: SynthReq) -> Response:
    if _voice is None:
        detail = (
            f"Voice model not available — {_load_error}"
            if _load_error
            else "Voice model not loaded"
        )
        raise HTTPException(status_code=503, detail=detail)

    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    # length_scale: higher = slower (inverse of speed)
    speed        = max(0.5, min(3.0, req.speed))
    length_scale = 1.0 / speed

    try:
        from piper.config import SynthesisConfig  # type: ignore
        syn_config = SynthesisConfig(length_scale=length_scale)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            # synthesize_wav() is the correct method in piper-tts 1.4.x
            # It sets the WAV format automatically from the first audio chunk
            _voice.synthesize_wav(text, wf, syn_config=syn_config)
        buf.seek(0)
        audio_bytes = buf.read()
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[piper] synthesize error for text={text!r}:\n{tb}", flush=True)
        raise HTTPException(
            status_code=500,
            detail=f"Synthesis error — {type(exc).__name__}: {exc}",
        )

    if len(audio_bytes) < 100:
        print(
            f"[piper] empty audio for text={text!r} ({len(audio_bytes)} bytes)",
            flush=True,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Piper produced empty audio ({len(audio_bytes)} bytes) "
                "— espeak-ng data may be missing"
            ),
        )

    return Response(content=audio_bytes, media_type="audio/wav")
