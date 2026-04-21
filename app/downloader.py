"""
Wrapper sobre yt-dlp: gerencia downloads em threads de background
e expõe progresso via dicionário em memória (progress_store).

DECISÃO ARQUITETURAL [2026-04-13]: Threading com dicionário em memória.
Motivo: baixa concorrência esperada (uso familiar). Sem necessidade de
Celery/Redis. Revisitar se volume de usuários simultâneos crescer.
"""

import os
import threading
from datetime import datetime
from typing import Any, Optional

import yt_dlp

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/app/downloads")

# Mapa em memória: {download_id: {status, percent, speed, eta, title, ...}}
# Lido pela rota SSE /api/progress/{id}
progress_store: dict[str, dict[str, Any]] = {}

# Flags de cancelamento: {download_id: threading.Event}
cancel_flags: dict[str, threading.Event] = {}

# ─── Opções de formato disponíveis ────────────────────────────────────────────

FORMAT_OPTIONS: dict[str, dict] = {
    "video-1080": {
        "label": "Vídeo 1080p (MP4)",
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
    },
    "video-720": {
        "label": "Vídeo 720p (MP4)",
        "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "merge_output_format": "mp4",
    },
    "video-480": {
        "label": "Vídeo 480p (MP4)",
        "format": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
        "merge_output_format": "mp4",
    },
    "audio-mp3": {
        "label": "Áudio MP3",
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    },
}

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def get_format_label(format_key: str) -> str:
    return FORMAT_OPTIONS.get(format_key, {}).get("label", format_key)


# ─── Informações de playlist (sem baixar) ─────────────────────────────────────

def get_playlist_info(url: str) -> dict:
    """Extrai metadados de playlist sem baixar. Retorna lista de entradas."""
    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "http_headers": {"User-Agent": _UA},
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info or info.get("_type") != "playlist":
        return {"is_playlist": False}

    entries = []
    for i, entry in enumerate(info.get("entries") or []):
        if not entry:
            continue
        duration = entry.get("duration")
        dur_str = ""
        if isinstance(duration, (int, float)) and duration > 0:
            total_s = int(duration)
            m, s = divmod(total_s, 60)
            h, m2 = divmod(m, 60)
            dur_str = f"{h}:{m2:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        entries.append({
            "index": i + 1,
            "title": entry.get("title") or f"Vídeo {i + 1}",
            "duration": dur_str,
            "uploader": entry.get("uploader") or entry.get("channel") or "",
        })

    return {
        "is_playlist": True,
        "title": info.get("title") or "Playlist",
        "count": len(entries),
        "entries": entries,
    }


# ─── Exceção interna de cancelamento ──────────────────────────────────────────

class _DownloadCancelled(Exception):
    pass


# ─── Lógica de download (roda em thread separada) ─────────────────────────────

def _run_download(
    download_id: str,
    url: str,
    format_key: str,
    playlist_items: Optional[str] = None,
) -> None:
    """Executa o download e atualiza progress_store e banco de dados."""
    from app.database import update_download  # import local para evitar circular

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Estado inicial
    progress_store[download_id] = {
        "status": "downloading",
        "percent": 0.0,
        "speed": "",
        "eta": "",
        "title": "Iniciando...",
        "filename": "",
        "error": None,
        "playlist_index": 0,
        "playlist_total": 0,
    }

    fmt = FORMAT_OPTIONS.get(format_key, FORMAT_OPTIONS["video-720"])
    cancel_event = cancel_flags.get(download_id, threading.Event())

    def progress_hook(d: dict) -> None:
        if cancel_event.is_set():
            raise _DownloadCancelled("Cancelado pelo usuário")

        store = progress_store[download_id]

        if d["status"] == "downloading":
            percent_raw = d.get("_percent_str", "0%").strip().replace("%", "")
            try:
                percent = float(percent_raw)
            except ValueError:
                percent = 0.0

            info = d.get("info_dict", {})
            store.update(
                {
                    "status": "downloading",
                    "percent": round(percent, 1),
                    "speed": d.get("_speed_str", "").strip(),
                    "eta": d.get("_eta_str", "").strip(),
                    "title": info.get("title", store["title"]),
                    "playlist_index": info.get("playlist_index") or 0,
                    "playlist_total": info.get("n_entries") or 0,
                }
            )

        elif d["status"] == "finished":
            info = d.get("info_dict", {})
            filename = os.path.basename(d.get("filename", ""))
            store.update(
                {
                    "percent": 99.0,  # conversão ffmpeg ainda pode ocorrer
                    "filename": filename,
                    "title": info.get("title", store["title"]),
                }
            )

    # Montar opções do yt-dlp
    ydl_opts: dict[str, Any] = {
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "format": fmt["format"],
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "geo_bypass": True,
        "extractor_retries": 3,
        "http_headers": {"User-Agent": _UA},
    }
    if "merge_output_format" in fmt:
        ydl_opts["merge_output_format"] = fmt["merge_output_format"]
    if "postprocessors" in fmt:
        ydl_opts["postprocessors"] = fmt["postprocessors"]
    if playlist_items:
        ydl_opts["playlist_items"] = playlist_items

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        title: str = info.get("title", "") if info else ""
        is_playlist = 1 if info and info.get("_type") == "playlist" else 0
        playlist_total = info.get("n_entries", 0) if info else 0

        filename = ""
        if info:
            requested = info.get("requested_downloads") or []
            if requested:
                filepath = requested[0].get("filepath", "")
                filename = os.path.basename(filepath)
            elif info.get("_type") == "playlist":
                entries = info.get("entries") or []
                for entry in reversed(entries):
                    if entry:
                        req = entry.get("requested_downloads") or []
                        if req:
                            filename = os.path.basename(req[0].get("filepath", ""))
                            break

        if not filename and os.path.exists(DOWNLOAD_DIR):
            files = sorted(
                [f for f in os.scandir(DOWNLOAD_DIR) if f.is_file()],
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if files:
                filename = files[0].name

        progress_store[download_id].update(
            {
                "status": "complete",
                "percent": 100.0,
                "title": title,
                "filename": filename,
                "speed": "",
                "eta": "",
            }
        )
        update_download(
            download_id,
            title=title,
            status="complete",
            filename=filename,
            is_playlist=is_playlist,
            playlist_total=playlist_total,
            completed_at=datetime.now().isoformat(),
        )

    except _DownloadCancelled:
        progress_store[download_id].update(
            {"status": "cancelled", "error": "Cancelado pelo usuário", "speed": "", "eta": ""}
        )
        update_download(download_id, status="cancelled")

    except Exception as exc:
        error_msg = str(exc)
        progress_store[download_id].update(
            {"status": "error", "error": error_msg}
        )
        update_download(download_id, status="error", error_msg=error_msg)

    finally:
        cancel_flags.pop(download_id, None)


def start_download(
    download_id: str,
    url: str,
    format_key: str,
    playlist_items: Optional[str] = None,
) -> None:
    """Inicia o download em uma thread daemon de background."""
    cancel_flags[download_id] = threading.Event()
    thread = threading.Thread(
        target=_run_download,
        args=(download_id, url, format_key, playlist_items),
        daemon=True,
        name=f"dl-{download_id[:8]}",
    )
    thread.start()


def cancel_download(download_id: str) -> bool:
    """Sinaliza cancelamento. Retorna True se havia um download ativo."""
    flag = cancel_flags.get(download_id)
    if flag:
        flag.set()
        return True
    return False
