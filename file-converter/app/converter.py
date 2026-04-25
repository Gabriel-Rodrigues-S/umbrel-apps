import io
import json
import os
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/output")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024

progress_store: dict[str, dict[str, Any]] = {}

FORMAT_OPTIONS: dict[str, dict] = {
    # ── Vídeo ──────────────────────────────────────────────────────
    "mp4-to-mkv":  {"label": "MP4 → MKV",              "type": "video",    "ext_in": "mp4",  "ext_out": "mkv"},
    "mkv-to-mp4":  {"label": "MKV → MP4",              "type": "video",    "ext_in": "mkv",  "ext_out": "mp4"},
    "mp4-to-avi":  {"label": "MP4 → AVI",              "type": "video",    "ext_in": "mp4",  "ext_out": "avi"},
    "any-to-mp3":  {"label": "Vídeo → MP3",            "type": "video",    "ext_in": None,   "ext_out": "mp3"},
    # ── Áudio ──────────────────────────────────────────────────────
    "mp3-to-wav":  {"label": "MP3 → WAV",              "type": "audio",    "ext_in": "mp3",  "ext_out": "wav"},
    "wav-to-mp3":  {"label": "WAV → MP3",              "type": "audio",    "ext_in": "wav",  "ext_out": "mp3"},
    "flac-to-mp3": {"label": "FLAC → MP3",             "type": "audio",    "ext_in": "flac", "ext_out": "mp3"},
    "any-to-flac": {"label": "Áudio → FLAC",           "type": "audio",    "ext_in": None,   "ext_out": "flac"},
    # ── Imagem ─────────────────────────────────────────────────────
    "png-to-jpg":  {"label": "PNG → JPG",              "type": "image",    "ext_in": "png",  "ext_out": "jpg"},
    "jpg-to-png":  {"label": "JPG → PNG",              "type": "image",    "ext_in": "jpg",  "ext_out": "png"},
    "webp-to-png": {"label": "WEBP → PNG",             "type": "image",    "ext_in": "webp", "ext_out": "png"},
    "webp-to-jpg": {"label": "WEBP → JPG",             "type": "image",    "ext_in": "webp", "ext_out": "jpg"},
    "jpg-to-webp": {"label": "JPG → WEBP",             "type": "image",    "ext_in": "jpg",  "ext_out": "webp"},
    "png-to-webp": {"label": "PNG → WEBP",             "type": "image",    "ext_in": "png",  "ext_out": "webp"},
    "img-to-pdf":  {"label": "Imagem → PDF",           "type": "image",    "ext_in": None,   "ext_out": "pdf"},
    # ── Documento ──────────────────────────────────────────────────
    "pdf-to-docx": {"label": "PDF → DOCX",             "type": "document", "ext_in": "pdf",  "ext_out": "docx"},
    "docx-to-pdf": {"label": "DOCX → PDF",             "type": "document", "ext_in": "docx", "ext_out": "pdf"},
    "pdf-to-png":  {"label": "PDF → PNG por página (ZIP)", "type": "document", "ext_in": "pdf", "ext_out": "zip"},
    "pdf-to-jpg":  {"label": "PDF → JPG por página (ZIP)", "type": "document", "ext_in": "pdf", "ext_out": "zip"},
    "pptx-to-pdf": {"label": "PPTX → PDF",             "type": "document", "ext_in": "pptx", "ext_out": "pdf"},
    "xlsx-to-pdf": {"label": "XLSX → PDF",             "type": "document", "ext_in": "xlsx", "ext_out": "pdf"},
}


def get_format_label(fmt_key: str) -> str:
    return FORMAT_OPTIONS.get(fmt_key, {}).get("label", fmt_key)


# ── Utilitários ───────────────────────────────────────────────────────────────

def _probe_duration(filepath: str) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", filepath],
            stderr=subprocess.DEVNULL, text=True,
        )
        return float(json.loads(out)["format"].get("duration", 0))
    except Exception:
        return 0.0


def _run_ffmpeg_with_progress(cmd: list[str], job_id: str, total_secs: float) -> None:
    full_cmd = cmd + ["-progress", "pipe:1", "-nostats"]
    proc = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                elapsed = int(line.split("=")[1]) / 1_000_000
                if total_secs > 0:
                    progress_store[job_id]["percent"] = min(99.0, round(elapsed / total_secs * 100, 1))
            except ValueError:
                pass
    proc.wait()
    if proc.returncode != 0:
        err = proc.stderr.read()
        raise RuntimeError(f"ffmpeg falhou (rc={proc.returncode}): {err[:400]}")


# ── Conversores por tipo ──────────────────────────────────────────────────────

def _convert_video(job_id: str, input_path: str, output_path: str, fmt_key: str) -> None:
    duration = _probe_duration(input_path)
    ext_out = FORMAT_OPTIONS[fmt_key]["ext_out"]
    if ext_out == "mp3":
        cmd = ["ffmpeg", "-y", "-i", input_path, "-vn", "-ab", "192k", output_path]
    else:
        cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path]
    _run_ffmpeg_with_progress(cmd, job_id, duration)


def _convert_audio(job_id: str, input_path: str, output_path: str, fmt_key: str) -> None:
    duration = _probe_duration(input_path)
    cmd = ["ffmpeg", "-y", "-i", input_path]
    ext_out = FORMAT_OPTIONS[fmt_key]["ext_out"]
    if ext_out == "mp3":
        cmd += ["-ab", "192k"]
    cmd.append(output_path)
    _run_ffmpeg_with_progress(cmd, job_id, duration)


def _convert_image(job_id: str, input_path: str, output_path: str, fmt_key: str) -> None:
    from PIL import Image
    progress_store[job_id]["percent"] = 10.0
    img = Image.open(input_path)
    ext_out = FORMAT_OPTIONS[fmt_key]["ext_out"]
    if ext_out in ("jpg", "jpeg", "pdf"):
        img = img.convert("RGB")
    img.save(output_path)
    progress_store[job_id]["percent"] = 99.0


def _convert_document(job_id: str, input_path: str, output_path: str, fmt_key: str) -> None:
    progress_store[job_id]["percent"] = 10.0

    if fmt_key == "pdf-to-docx":
        from pdf2docx import Converter
        cv = Converter(input_path)
        cv.convert(output_path)
        cv.close()

    elif fmt_key in ("docx-to-pdf", "pptx-to-pdf", "xlsx-to-pdf"):
        out_dir = str(Path(output_path).parent)
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", out_dir, input_path],
            check=True, capture_output=True,
        )
        lo_output = Path(out_dir) / f"{Path(input_path).stem}.pdf"
        os.rename(lo_output, output_path)

    elif fmt_key in ("pdf-to-png", "pdf-to-jpg"):
        from pdf2image import convert_from_path
        img_format = "PNG" if fmt_key == "pdf-to-png" else "JPEG"
        img_ext = "png" if fmt_key == "pdf-to-png" else "jpg"
        pages = convert_from_path(input_path, dpi=150)
        if len(pages) == 1:
            actual_path = str(Path(output_path).with_suffix(f".{img_ext}"))
            page = pages[0].convert("RGB") if img_format == "JPEG" else pages[0]
            page.save(actual_path, format=img_format, quality=90)
            progress_store[job_id]["percent"] = 98.0
            return actual_path
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, page in enumerate(pages):
                buf = io.BytesIO()
                if img_format == "JPEG":
                    page = page.convert("RGB")
                page.save(buf, format=img_format, quality=90)
                zf.writestr(f"page_{i+1:04d}.{img_ext}", buf.getvalue())
                progress_store[job_id]["percent"] = round((i + 1) / len(pages) * 98, 1)

    progress_store[job_id]["percent"] = 99.0


# ── Thread principal ──────────────────────────────────────────────────────────

def _run_conversion(job_id: str, input_path: str, fmt_key: str) -> None:
    from app.database import update_conversion

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stem = Path(input_path).stem
    ext_out = FORMAT_OPTIONS[fmt_key]["ext_out"]
    output_filename = f"{stem}_converted_{job_id[:8]}.{ext_out}"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    conv_type = FORMAT_OPTIONS[fmt_key]["type"]

    progress_store[job_id] = {"status": "converting", "percent": 0.0, "filename": "", "error": None}

    try:
        if conv_type == "video":
            _convert_video(job_id, input_path, output_path, fmt_key)
        elif conv_type == "audio":
            _convert_audio(job_id, input_path, output_path, fmt_key)
        elif conv_type == "image":
            _convert_image(job_id, input_path, output_path, fmt_key)
        elif conv_type == "document":
            actual = _convert_document(job_id, input_path, output_path, fmt_key)
            if actual:
                output_path = actual
                output_filename = Path(output_path).name

        filesize_out = os.path.getsize(output_path)
        progress_store[job_id].update({"status": "complete", "percent": 100.0, "filename": output_filename})
        update_conversion(
            job_id,
            status="complete",
            output_filename=output_filename,
            filesize_out=filesize_out,
            completed_at=datetime.now().isoformat(),
        )

    except Exception as exc:
        error_msg = str(exc)
        progress_store[job_id].update({"status": "error", "error": error_msg})
        update_conversion(job_id, status="error", error_msg=error_msg)

    finally:
        try:
            os.remove(input_path)
        except OSError:
            pass


def start_conversion(job_id: str, input_path: str, fmt_key: str) -> None:
    thread = threading.Thread(
        target=_run_conversion,
        args=(job_id, input_path, fmt_key),
        daemon=True,
        name=f"conv-{job_id[:8]}",
    )
    thread.start()


# ── Limpeza automática ────────────────────────────────────────────────────────

def start_cleanup_thread() -> None:
    def _cleanup():
        max_age = 2 * 3600
        while True:
            time.sleep(3600)
            now = time.time()
            for directory in (OUTPUT_DIR, UPLOAD_DIR):
                if not os.path.exists(directory):
                    continue
                for entry in os.scandir(directory):
                    if entry.is_file() and (now - entry.stat().st_mtime) > max_age:
                        try:
                            os.remove(entry.path)
                        except OSError:
                            pass

    thread = threading.Thread(target=_cleanup, daemon=True, name="cleanup")
    thread.start()
