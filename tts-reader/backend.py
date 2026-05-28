"""
TTS Reader — Piper TTS backend
POST /synthesize  { text: str, speed: float }  → audio/wav
GET  /health                                    → { ready: bool, voice: str }
"""
from __future__ import annotations

import io
import wave
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────
MODEL_DIR  = Path("/app/models")
MODEL_NAME = "pt_BR-faber-medium"
MODEL_PATH = MODEL_DIR / f"{MODEL_NAME}.onnx"

app = FastAPI()
_voice = None


def _load_voice() -> None:
    global _voice
    try:
        from piper.voice import PiperVoice  # type: ignore
        _voice = PiperVoice.load(str(MODEL_PATH))
        print(f"[piper] model loaded: {MODEL_PATH}", flush=True)
    except Exception as exc:
        print(f"[piper] load error: {exc}", flush=True)
        _voice = None


_load_voice()


# ── Schema ────────────────────────────────────────────────────────────────
class SynthReq(BaseModel):
    text: str
    speed: float = 1.0


# ── Endpoints ─────────────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    return {"ready": _voice is not None, "voice": MODEL_NAME}


@app.post("/synthesize")
def synthesize(req: SynthReq) -> Response:
    if _voice is None:
        raise HTTPException(status_code=503, detail="Voice model not available")

    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    # length_scale: higher = slower (inverse of speed)
    speed        = max(0.5, min(3.0, req.speed))
    length_scale = 1.0 / speed

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        # synthesize() is a generator — must be fully consumed to write audio frames
        for _ in _voice.synthesize(text, wf, length_scale=length_scale):
            pass
    buf.seek(0)

    audio_bytes = buf.read()
    if len(audio_bytes) < 100:
        raise HTTPException(status_code=500, detail="Piper produced empty audio")

    return Response(content=audio_bytes, media_type="audio/wav")
