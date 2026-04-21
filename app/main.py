"""
Aplicação FastAPI principal.
Rotas:
  GET  /                          → UI (index.html)
  POST /api/playlist-info         → extrai metadados de playlist sem baixar
  POST /api/download              → inicia download, retorna download_id
  POST /api/cancel/{id}           → cancela download em andamento
  GET  /api/progress/{id}         → SSE stream de progresso
  GET  /api/history               → histórico de downloads (SQLite)
  GET  /api/files                 → lista arquivos na pasta de downloads
  GET  /files/{filename}          → serve arquivo para download direto
  DELETE /api/downloads/{id}      → remove registro do histórico
"""

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from app.database import (
    create_download,
    delete_download_record,
    get_history,
    init_db,
    update_download,
)
from app.downloader import (
    DOWNLOAD_DIR,
    cancel_download,
    get_format_label,
    get_playlist_info,
    progress_store,
    start_download,
)

app = FastAPI(title="YT Downloader", version="1.0.0")

TEMPLATES_DIR = Path(__file__).parent / "templates"


# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ─── Frontend ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> str:
    html_path = TEMPLATES_DIR / "index.html"
    return html_path.read_text(encoding="utf-8")


# ─── API: info de playlist ─────────────────────────────────────────────────────

class PlaylistInfoRequest(BaseModel):
    url: str


@app.post("/api/playlist-info")
async def api_playlist_info(req: PlaylistInfoRequest) -> dict:
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL não pode ser vazia.")
    try:
        result = await asyncio.to_thread(get_playlist_info, url)
        return result
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ─── API: iniciar download ─────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    url: str
    format: str = "video-720"
    playlist_items: Optional[str] = None  # ex: "1,3,5-7"


@app.post("/api/download")
async def api_start_download(req: DownloadRequest) -> dict:
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL não pode ser vazia.")

    allowed_formats = {"video-1080", "video-720", "video-480", "audio-mp3"}
    if req.format not in allowed_formats:
        raise HTTPException(status_code=400, detail="Formato inválido.")

    download_id = str(uuid.uuid4())
    format_label = get_format_label(req.format)

    create_download(download_id, url, format_label)
    start_download(download_id, url, req.format, req.playlist_items)

    return {"download_id": download_id, "status": "started"}


# ─── API: cancelar download ────────────────────────────────────────────────────

@app.post("/api/cancel/{download_id}")
async def api_cancel(download_id: str) -> dict:
    found = cancel_download(download_id)
    if not found:
        # Pode já ter terminado — não é erro
        return {"status": "not_active"}
    return {"status": "cancelling"}


# ─── API: progresso via SSE ────────────────────────────────────────────────────

@app.get("/api/progress/{download_id}")
async def api_progress(download_id: str) -> StreamingResponse:
    """
    Server-Sent Events: envia atualizações de progresso ao cliente.
    O cliente usa EventSource() para ouvir esta rota.
    """

    async def event_stream():
        # Aguarda até o download aparecer no store (max 10s)
        waited = 0.0
        while download_id not in progress_store and waited < 10:
            await asyncio.sleep(0.3)
            waited += 0.3

        while True:
            data = progress_store.get(download_id)
            if data is None:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                break

            yield f"data: {json.dumps(data)}\n\n"

            if data.get("status") in ("complete", "error", "cancelled"):
                break

            await asyncio.sleep(0.8)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # evita buffer no nginx/proxy
            "Connection": "keep-alive",
        },
    )


# ─── API: histórico ────────────────────────────────────────────────────────────

@app.get("/api/history")
async def api_history() -> list[dict]:
    return get_history()


# ─── API: listar arquivos ──────────────────────────────────────────────────────

@app.get("/api/files")
async def api_files() -> list[dict]:
    if not os.path.exists(DOWNLOAD_DIR):
        return []

    files = []
    for entry in os.scandir(DOWNLOAD_DIR):
        if entry.is_file():
            stat = entry.stat()
            files.append(
                {
                    "filename": entry.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )

    return sorted(files, key=lambda f: f["modified"], reverse=True)


# ─── Servir arquivo para download ─────────────────────────────────────────────

@app.get("/files/{filename:path}")
async def serve_file(filename: str) -> FileResponse:
    filepath = Path(DOWNLOAD_DIR) / filename

    # Segurança: previne path traversal
    try:
        filepath.resolve().relative_to(Path(DOWNLOAD_DIR).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/octet-stream",
    )


# ─── Deletar registro do histórico ────────────────────────────────────────────

@app.delete("/api/downloads/{download_id}")
async def api_delete(download_id: str) -> dict:
    delete_download_record(download_id)
    progress_store.pop(download_id, None)
    return {"status": "deleted"}
