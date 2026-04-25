"""
FastAPI — File Converter
Rotas:
  GET  /                          → UI (index.html)
  POST /api/convert               → upload + conversão (arquivo único)
  POST /api/convert-batch         → upload + conversão (múltiplos arquivos)
  GET  /api/progress/{id}         → SSE stream de progresso
  GET  /api/batch-zip             → baixar vários arquivos em um ZIP
  GET  /api/history               → histórico de conversões (SQLite)
  GET  /api/files                 → lista arquivos em OUTPUT_DIR
  GET  /files/{filename}          → serve arquivo para download
  DELETE /api/conversions/{id}    → remove registro do histórico
"""

import asyncio
import io as _io
import json
import os
import uuid
import zipfile as _zipfile
from pathlib import Path
from typing import List

import aiofiles
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from app.converter import (
    FORMAT_OPTIONS,
    MAX_UPLOAD_BYTES,
    OUTPUT_DIR,
    UPLOAD_DIR,
    get_format_label,
    progress_store,
    start_cleanup_thread,
    start_conversion,
    start_merge,
)
from app.database import (
    create_conversion,
    delete_conversion_record,
    get_history,
    init_db,
)

app = FastAPI(title="File Converter", version="1.0.0")

TEMPLATES_DIR = Path(__file__).parent / "templates"


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    start_cleanup_thread()
    # Aquece o LibreOffice para evitar delay na primeira conversão
    import subprocess
    subprocess.run(["libreoffice", "--headless", "--version"], capture_output=True)


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> str:
    return (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")


# ── API: iniciar conversão ────────────────────────────────────────────────────

@app.post("/api/convert")
async def api_start_conversion(
    file: UploadFile = File(...),
    format: str = Form(...),
) -> dict:
    if format not in FORMAT_OPTIONS:
        raise HTTPException(status_code=400, detail="Formato inválido.")

    fmt_info = FORMAT_OPTIONS[format]
    expected_ext = fmt_info.get("ext_in")
    if expected_ext:
        actual_ext = Path(file.filename or "").suffix.lstrip(".").lower()
        if actual_ext != expected_ext:
            raise HTTPException(
                status_code=400,
                detail=f"Este formato espera um arquivo .{expected_ext}, recebeu .{actual_ext}.",
            )

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Arquivo muito grande.")

    job_id = str(uuid.uuid4())
    original_filename = file.filename or "upload"
    stem = Path(original_filename).stem
    ext = Path(original_filename).suffix
    saved_name = f"{stem}_{job_id[:8]}{ext}"
    input_path = os.path.join(UPLOAD_DIR, saved_name)

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    async with aiofiles.open(input_path, "wb") as f:
        await f.write(content)

    create_conversion(
        job_id,
        original_filename=original_filename,
        input_format=fmt_info.get("ext_in") or Path(original_filename).suffix.lstrip(".").lower(),
        output_format=fmt_info["ext_out"],
        conversion_type=fmt_info["type"],
        filesize_in=os.path.getsize(input_path),
    )
    start_conversion(job_id, input_path, format)

    return {"job_id": job_id, "status": "started"}


# ── API: conversão em lote ───────────────────────────────────────────────────

@app.post("/api/convert-batch")
async def api_start_batch_conversion(
    files: List[UploadFile] = File(...),
    format: str = Form(...),
    mode: str = Form(...),
) -> dict:
    if mode not in ("individual", "merge"):
        raise HTTPException(status_code=400, detail="Modo inválido.")
    if not files:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")
    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Máximo de 50 arquivos por vez.")

    # Salva todos os arquivos em disco
    saved: list[tuple[str, str, int]] = []  # (path, original_name, size)
    for file in files:
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"{file.filename}: arquivo muito grande.")
        original_filename = file.filename or "upload"
        tid = str(uuid.uuid4())[:8]
        saved_name = f"{Path(original_filename).stem}_{tid}{Path(original_filename).suffix}"
        input_path = os.path.join(UPLOAD_DIR, saved_name)
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        async with aiofiles.open(input_path, "wb") as f:
            await f.write(content)
        saved.append((input_path, original_filename, os.path.getsize(input_path)))

    if mode == "merge":
        job_id = str(uuid.uuid4())
        input_paths = [s[0] for s in saved]
        create_conversion(
            job_id,
            original_filename=f"{len(saved)} arquivo(s) → PDF",
            input_format="mixed",
            output_format="pdf",
            conversion_type="batch-merge",
            filesize_in=sum(s[2] for s in saved),
        )
        start_merge(job_id, input_paths)
        return {"mode": "merge", "job_id": job_id}

    # mode == "individual"
    if format not in FORMAT_OPTIONS:
        raise HTTPException(status_code=400, detail="Formato inválido.")
    fmt_info = FORMAT_OPTIONS[format]
    jobs = []
    for input_path, original_filename, size in saved:
        expected_ext = fmt_info.get("ext_in")
        if expected_ext:
            actual_ext = Path(original_filename).suffix.lstrip(".").lower()
            if actual_ext != expected_ext:
                raise HTTPException(
                    status_code=400,
                    detail=f"{original_filename}: esperado .{expected_ext}, recebeu .{actual_ext}.",
                )
        job_id = str(uuid.uuid4())
        create_conversion(
            job_id,
            original_filename=original_filename,
            input_format=fmt_info.get("ext_in") or Path(original_filename).suffix.lstrip(".").lower(),
            output_format=fmt_info["ext_out"],
            conversion_type=fmt_info["type"],
            filesize_in=size,
        )
        start_conversion(job_id, input_path, format)
        jobs.append({"job_id": job_id, "filename": original_filename})
    return {"mode": "individual", "jobs": jobs}


# ── API: baixar múltiplos arquivos como ZIP ───────────────────────────────────

@app.get("/api/batch-zip")
async def api_batch_zip(files: str) -> StreamingResponse:
    filenames = [f.strip() for f in files.split(",") if f.strip()]
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
        for filename in filenames:
            filepath = Path(OUTPUT_DIR) / filename
            try:
                filepath.resolve().relative_to(Path(OUTPUT_DIR).resolve())
            except ValueError:
                continue
            if filepath.exists():
                zf.write(filepath, filename)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="arquivos_convertidos.zip"'},
    )


# ── API: progresso via SSE ────────────────────────────────────────────────────

@app.get("/api/progress/{job_id}")
async def api_progress(job_id: str) -> StreamingResponse:
    async def event_stream():
        waited = 0.0
        while job_id not in progress_store and waited < 10:
            await asyncio.sleep(0.3)
            waited += 0.3

        while True:
            data = progress_store.get(job_id)
            if data is None:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                break

            yield f"data: {json.dumps(data)}\n\n"

            if data.get("status") in ("complete", "error"):
                break

            await asyncio.sleep(0.8)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── API: histórico ────────────────────────────────────────────────────────────

@app.get("/api/history")
async def api_history() -> list[dict]:
    return get_history()


# ── API: listar arquivos ──────────────────────────────────────────────────────

@app.get("/api/files")
async def api_files() -> list[dict]:
    if not os.path.exists(OUTPUT_DIR):
        return []
    files = []
    for entry in os.scandir(OUTPUT_DIR):
        if entry.is_file():
            stat = entry.stat()
            files.append({"filename": entry.name, "size": stat.st_size, "modified": stat.st_mtime})
    return sorted(files, key=lambda f: f["modified"], reverse=True)


# ── Servir arquivo ────────────────────────────────────────────────────────────

@app.get("/files/{filename:path}")
async def serve_file(filename: str) -> FileResponse:
    filepath = Path(OUTPUT_DIR) / filename
    try:
        filepath.resolve().relative_to(Path(OUTPUT_DIR).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado.")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(path=str(filepath), filename=filename, media_type="application/octet-stream")


# ── Deletar registro ──────────────────────────────────────────────────────────

@app.delete("/api/conversions/{job_id}")
async def api_delete(job_id: str) -> dict:
    delete_conversion_record(job_id)
    progress_store.pop(job_id, None)
    return {"status": "deleted"}
