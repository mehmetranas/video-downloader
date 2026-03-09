"""
video-downloader — FastAPI application
All routes, models, registry, and scheduler in a single file (by design).
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Security
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


# POST /download and GET /files/{file_id} will be added in Plan 02
