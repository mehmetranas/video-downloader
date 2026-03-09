"""
video-downloader — FastAPI application
All routes, models, registry, and scheduler in a single file (by design).
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import asyncio
import glob
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import yt_dlp
from pydantic import BaseModel

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.exceptions import HTTPException as StarletteHTTPException

# ---------------------------------------------------------------------------
# Env var loading
# ---------------------------------------------------------------------------
load_dotenv()

API_KEY: str = os.environ.get("API_KEY", "")

# ---------------------------------------------------------------------------
# Startup guard
# ---------------------------------------------------------------------------
if not API_KEY:
    raise RuntimeError("API_KEY env var must be set")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DOWNLOAD_DIR: str = os.environ.get("DOWNLOAD_DIR", "/tmp/downloads")
TTL_HOURS: int = 1

QUALITY_MAP: dict[str, str] = {
    "best":       "bestvideo+bestaudio/best",
    "1080p":      "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p":       "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p":       "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "audio-only": "bestaudio/best",
}

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("video-downloader")

# ---------------------------------------------------------------------------
# FileRecord dataclass
# ---------------------------------------------------------------------------
@dataclass
class FileRecord:
    file_id: str
    path: str
    filename: str
    title: str
    duration: int
    expires_at: datetime
    content_type: str


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------
class DownloadRequest(BaseModel):
    url: str
    quality: Literal["best", "1080p", "720p", "480p", "audio-only"] = "best"


class DownloadResponse(BaseModel):
    download_url: str
    expires_at: datetime
    filename: str
    title: str
    duration: int


# ---------------------------------------------------------------------------
# Playlist detection helper (synchronous — call via asyncio.to_thread)
# ---------------------------------------------------------------------------
def _check_playlist(url: str) -> bool:
    """Returns True if the URL resolves to a playlist. Synchronous — use via asyncio.to_thread."""
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
    return info.get("_type") == "playlist"


# ---------------------------------------------------------------------------
# FileRegistry — module-level dict + lock
# ---------------------------------------------------------------------------
files: dict[str, FileRecord] = {}
registry_lock = threading.Lock()


def register_file(record: FileRecord) -> None:
    """Add a FileRecord to the registry."""
    with registry_lock:
        files[record.file_id] = record


def get_file(file_id: str) -> FileRecord | None:
    """Return FileRecord by ID, or None if not found."""
    with registry_lock:
        return files.get(file_id)


def cleanup_expired() -> None:
    """Remove expired files from registry and disk.

    Acquires the lock only to collect expired keys, then releases before
    performing disk I/O to avoid holding the lock during slow operations.
    """
    now = datetime.utcnow()
    with registry_lock:
        expired_keys = [k for k, v in files.items() if v.expires_at < now]

    for key in expired_keys:
        with registry_lock:
            record = files.pop(key, None)
        if record is not None:
            try:
                os.remove(record.path)
                logger.info("Cleaned up expired file: %s", record.path)
            except FileNotFoundError:
                pass  # Already gone — that is fine
            except OSError as exc:
                logger.warning("Failed to remove file %s: %s", record.path, exc)


# ---------------------------------------------------------------------------
# APScheduler
# ---------------------------------------------------------------------------
scheduler = BackgroundScheduler()


# ---------------------------------------------------------------------------
# Lifespan context manager
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(cleanup_expired, IntervalTrigger(minutes=5))
    scheduler.start()
    logger.info("Cleanup scheduler started (interval: 5 min)")
    yield
    scheduler.shutdown()
    logger.info("Cleanup scheduler stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Video Downloader",
    description="Send a video URL, get a 1-hour temporary download link.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Exception handlers — structured JSON only, never raw tracebacks
# ---------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "Validation error", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(key: str = Security(api_key_header)) -> str:
    """Raise 401 if X-API-Key header is missing or does not match API_KEY."""
    if not key or key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
        )
    return key


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Health check — no authentication required."""
    return {"status": "ok"}


def download_video(url: str, quality: str, file_id: str) -> dict:
    """Synchronous yt-dlp download. Call via asyncio.to_thread — never call directly from async."""
    is_audio_only = quality == "audio-only"
    ydl_opts = {
        "format": QUALITY_MAP[quality],
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if not is_audio_only:
        ydl_opts["merge_output_format"] = "mp4"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Find actual output file (extension may differ from outtmpl due to postprocessors)
    matches = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_id}.*"))
    if not matches:
        raise RuntimeError(f"Download completed but output file not found for {file_id}")
    actual_path = matches[0]
    actual_filename = os.path.basename(actual_path)
    content_type = "audio/mp4" if is_audio_only else "video/mp4"

    return {
        "path": actual_path,
        "filename": actual_filename,
        "title": info.get("title", "video"),
        "duration": int(info.get("duration") or 0),
        "content_type": content_type,
    }


@app.post("/download", response_model=DownloadResponse)
async def download(request: Request, body: DownloadRequest, _: str = Depends(verify_api_key)):
    # Playlist check (runs in thread to avoid blocking event loop)
    is_playlist = await asyncio.to_thread(_check_playlist, body.url)
    if is_playlist:
        raise HTTPException(status_code=422, detail="Playlist URLs are not supported")

    file_id = str(uuid.uuid4())
    result = await asyncio.to_thread(download_video, body.url, body.quality, file_id)

    expires_at = datetime.utcnow() + timedelta(hours=TTL_HOURS)
    record = FileRecord(
        file_id=file_id,
        path=result["path"],
        filename=result["filename"],
        title=result["title"],
        duration=result["duration"],
        expires_at=expires_at,
        content_type=result["content_type"],
    )
    register_file(record)

    download_url = str(request.base_url) + f"files/{file_id}"
    return DownloadResponse(
        download_url=download_url,
        expires_at=expires_at,
        filename=result["filename"],
        title=result["title"],
        duration=result["duration"],
    )


@app.get("/files/{file_id}")
async def serve_file(file_id: str, _: str = Depends(verify_api_key)):
    record = get_file(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="File has expired")
    if not os.path.exists(record.path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(
        path=record.path,
        filename=record.filename,
        media_type=record.content_type,
    )
