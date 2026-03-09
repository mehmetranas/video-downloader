# Phase 1: Core Application - Research

**Researched:** 2026-03-09
**Domain:** FastAPI + yt-dlp + APScheduler — synchronous video download API with in-memory file registry
**Confidence:** MEDIUM-HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Single `main.py` — all routes, models, and logic in one file
- No modular package split (routers/, services/) — unnecessary for this scope
- yt-dlp invocation extracted into a `download_video()` helper function; route handlers stay thin
- FileRegistry implemented as a module-level dict: `files: dict[str, FileRecord] = {}`
- Dependencies managed via `requirements.txt`

### Claude's Discretion
- File storage directory location and naming scheme
- Quality fallback behavior (when requested quality unavailable)
- Exact JSON error response shape (fields, format)
- Logging approach
- Background scheduler implementation (APScheduler vs asyncio loop)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DL-01 | POST /download accepts video URL + quality param (best/1080p/720p/480p/audio-only) | yt-dlp format selection syntax; quality→format string mapping pattern |
| DL-02 | Successful download returns JSON: download_url, expires_at, filename, title, duration | yt-dlp extract_info fields (title, duration); UUID-based file storage design |
| FILE-01 | GET /files/{id} returns binary file with correct Content-Type and Content-Disposition | FastAPI FileResponse with filename parameter auto-sets Content-Disposition |
| FILE-02 | GET /files/{id} returns 404 (not found) or 410 (expired) | FileRegistry lookup logic; distinct 404 vs 410 status codes |
| SEC-01 | All endpoints except GET /health require X-API-Key header validation | FastAPI APIKeyHeader + Security Depends pattern; 401 HTTPException |
| SEC-02 | Playlist URLs return 422 | yt-dlp extract_info with download=False; check info.get('_type') == 'playlist' |
| OPS-01 | Files auto-deleted after 1-hour TTL; cleanup runs every 5 minutes | APScheduler BackgroundScheduler with IntervalTrigger; os.remove + dict cleanup |
| OPS-02 | GET /health returns 200 for Coolify health checks | Simple route returning {"status": "ok"}; excluded from API key requirement |
| OPS-03 | All API errors return structured JSON; never raw tracebacks | @app.exception_handler overrides for HTTPException + RequestValidationError + Exception |
</phase_requirements>

---

## Summary

This phase builds a single-file FastAPI service that wraps yt-dlp for synchronous video download. The architecture is intentionally minimal: one Python file, an in-memory dict as the file registry, and a background scheduler for cleanup. The main technical challenges are (1) preventing yt-dlp from blocking the asyncio event loop, (2) reliably getting the output filename after download (yt-dlp's `prepare_filename()` has known bugs with postprocessors), and (3) detecting playlist URLs before download begins.

The standard stack is well-understood and production-stable: FastAPI 0.135.1, yt-dlp 2026.3.3, APScheduler 3.11.2. All three libraries have HIGH confidence sources. The critical operational risk flagged in STATE.md is the YouTube PO Token requirement in server/Docker environments — yt-dlp may receive HTTP 403 errors from YouTube in containerized contexts. This should be treated as P0 validation immediately in Phase 1.

**Primary recommendation:** Use `asyncio.to_thread()` (Python 3.9+) to wrap `ydl.extract_info()` and avoid blocking the event loop. Use UUID-prefixed `outtmpl` for deterministic output filenames instead of relying on `prepare_filename()`. Use APScheduler `BackgroundScheduler` with `IntervalTrigger` started before the FastAPI app and shut down via lifespan context manager.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | 0.135.1 | HTTP framework, routing, dependency injection, OpenAPI docs | De-facto Python async API framework; native Pydantic v2 support |
| uvicorn[standard] | latest | ASGI server | FastAPI's official recommended server |
| yt-dlp | 2026.3.3 | Video download and metadata extraction | Actively maintained youtube-dl fork; supports 1000+ sites |
| APScheduler | 3.11.2 | Background cleanup scheduler | Production/stable; v4 still in alpha (4.0.0a6); BackgroundScheduler is thread-safe |
| pydantic | (bundled with fastapi) | Request/response validation, models | Built into FastAPI; use BaseModel for all schemas |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | latest | .env file loading for API_KEY | Load env vars in dev without Docker |
| python-multipart | latest | FastAPI file upload support | Required if any multipart handling; include defensively |
| ffmpeg (system dep) | any | yt-dlp: merge video+audio, transcode | Required for quality formats that need merge (1080p etc.) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| APScheduler BackgroundScheduler | asyncio.create_task + while loop | asyncio loop is simpler code but less robust; no cron/interval abstraction, harder to cancel |
| APScheduler BackgroundScheduler | APScheduler AsyncIOScheduler | AsyncIOScheduler shares event loop — blocks async if cleanup takes time; BackgroundScheduler runs in a separate thread, safer for file I/O |
| asyncio.to_thread() | loop.run_in_executor(ThreadPoolExecutor) | Functionally equivalent; `asyncio.to_thread()` is cleaner Python 3.9+ syntax |
| UUID-prefix outtmpl | prepare_filename() | prepare_filename() has known bugs with postprocessors (Issue #9030, #5517); UUID prefix is deterministic |

**Installation:**
```bash
pip install "fastapi[standard]" yt-dlp apscheduler python-dotenv python-multipart
# System: apt-get install ffmpeg  (or brew install ffmpeg on macOS)
```

---

## Architecture Patterns

### Recommended Project Structure
```
video-downloader/
├── main.py              # All routes, models, helpers, scheduler
├── requirements.txt     # Python dependencies
├── .env                 # API_KEY=... (dev only, gitignored)
└── downloads/           # Temp file storage (auto-created, gitignored)
```

### Pattern 1: Async yt-dlp Invocation (CRITICAL)
**What:** yt-dlp's `YoutubeDL.extract_info()` is synchronous and CPU+IO bound. Calling it directly from an `async def` route blocks the entire event loop.
**When to use:** Always — every download call must go through `asyncio.to_thread()`.
**Example:**
```python
import asyncio
import yt_dlp

async def download_video(url: str, quality: str, output_dir: str) -> dict:
    def _blocking_download():
        ydl_opts = {
            "format": QUALITY_MAP[quality],
            "outtmpl": f"{output_dir}/{file_id}.%(ext)s",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        return info

    info = await asyncio.to_thread(_blocking_download)
    return info
```
**Source:** Python 3.9+ asyncio docs; yt-dlp/issues/9487 confirms ProcessPoolExecutor causes pickling errors — use ThreadPoolExecutor (which `asyncio.to_thread` uses internally).

### Pattern 2: Playlist Detection Before Download
**What:** Call `extract_info(url, download=False)` with `process=False` to cheaply detect if URL resolves to a playlist.
**When to use:** At the start of POST /download, before any download begins.
**Example:**
```python
def _check_playlist(url: str) -> bool:
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
    return info.get("_type") == "playlist"
```
**Caveat (MEDIUM confidence):** The `_type == "playlist"` check is the standard approach but may miss some edge cases (e.g., Twitter single-video URLs treated as playlist in yt-dlp issue #15402). Use as primary guard; `noplaylist: True` in download opts as secondary safety.

### Pattern 3: UUID-Based File Storage
**What:** Use `file_id = str(uuid.uuid4())` as both the registry key and the `outtmpl` prefix. After download, glob for `{file_id}.*` to find the actual file (extension determined by yt-dlp after merge).
**Why:** `prepare_filename()` returns wrong extensions when postprocessors run (issues #9030, #5517). UUID prefix makes the file uniquely findable.
**Example:**
```python
import uuid, glob, os

file_id = str(uuid.uuid4())
outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

# After download, find actual file:
matches = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_id}.*"))
actual_path = matches[0]  # There should be exactly one
```

### Pattern 4: In-Memory FileRegistry with threading.Lock
**What:** Module-level dict protected by `threading.Lock` for thread-safe reads/writes. APScheduler's BackgroundScheduler runs in a daemon thread; the lock prevents race conditions during cleanup vs. serving.
**Example:**
```python
import threading
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class FileRecord:
    file_id: str
    path: str
    filename: str
    title: str
    duration: int
    expires_at: datetime
    content_type: str

files: dict[str, FileRecord] = {}
registry_lock = threading.Lock()

def register_file(record: FileRecord) -> None:
    with registry_lock:
        files[record.file_id] = record

def get_file(file_id: str) -> FileRecord | None:
    with registry_lock:
        return files.get(file_id)

def cleanup_expired() -> None:
    now = datetime.utcnow()
    with registry_lock:
        expired = [k for k, v in files.items() if v.expires_at < now]
    for key in expired:
        record = files.pop(key, None)
        if record and os.path.exists(record.path):
            os.remove(record.path)
```

### Pattern 5: APScheduler Lifespan Integration
**What:** Start BackgroundScheduler before lifespan yield; shut it down after. IntervalTrigger every 5 minutes.
**Example:**
```python
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(cleanup_expired, IntervalTrigger(minutes=5))
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
```
**Source:** APScheduler 3.11.2 docs (https://apscheduler.readthedocs.io/en/3.x/); Sentry FastAPI scheduling guide.

### Pattern 6: X-API-Key Authentication Dependency
**What:** FastAPI Security dependency using `APIKeyHeader`. Raises HTTP 401 if header missing or wrong.
**Example:**
```python
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

API_KEY = os.environ.get("API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(key: str = Security(api_key_header)) -> str:
    if not key or key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return key
```
Apply to protected routes: `@app.post("/download", dependencies=[Depends(verify_api_key)])`.
GET /health does NOT include this dependency.

### Pattern 7: Structured JSON Error Responses (OPS-03)
**What:** Override FastAPI's default exception handlers to ensure all errors return `{"error": "...", "detail": "..."}` — never raw tracebacks.
**Example:**
```python
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )
```
**Source:** https://fastapi.tiangolo.com/tutorial/handling-errors/

### Pattern 8: Quality → yt-dlp Format String Mapping
```python
QUALITY_MAP = {
    "best":       "bestvideo+bestaudio/best",
    "1080p":      "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p":       "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p":       "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "audio-only": "bestaudio/best",
}
```
The `/best[height<=N]` fallback handles sites that don't split video+audio streams. ffmpeg must be installed for merge formats.

### Anti-Patterns to Avoid
- **Calling yt-dlp directly in async def without to_thread:** Blocks the event loop; all concurrent requests hang.
- **Using prepare_filename() to find output file:** Known buggy with postprocessors; use UUID glob pattern instead.
- **Starting APScheduler in module-level code outside lifespan:** Scheduler starts at import time, runs during tests, can't be properly shut down.
- **Using ProcessPoolExecutor for yt-dlp:** Causes pickling errors with TextIOWrapper (yt-dlp issue #9487).
- **Returning 403 for missing API key:** Standard is 401 for missing/invalid credentials; 403 is for authenticated but unauthorized.
- **Hardcoding API_KEY:** Must read from env var (`os.environ.get("API_KEY")`) — Phase 2 will containerize.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Video download + quality selection | Custom HTTP video fetcher | yt-dlp YoutubeDL | Handles 1000+ sites, adaptive streams, format merging, cookies, rate limiting |
| Scheduled cleanup | asyncio sleep loop | APScheduler BackgroundScheduler | Proper thread management, error isolation, testable, survives exceptions |
| API key extraction from headers | Manual request.headers.get() | FastAPI APIKeyHeader + Security | Auto-documents in OpenAPI; handles header case-insensitivity |
| Thread-safe dict | Custom lock wrapper class | threading.Lock + plain dict | Python's dict GIL + explicit Lock is sufficient for this scale |
| HTTP file serving | Manual open() + read() chunks | FastAPI FileResponse | Handles Content-Length, ETag, Last-Modified, range requests automatically |

**Key insight:** yt-dlp's complexity (adaptive streams, merging, site-specific extractors, format negotiation) would take months to replicate. Never bypass it.

---

## Common Pitfalls

### Pitfall 1: Blocking Event Loop with yt-dlp
**What goes wrong:** Defining the route as `async def` and calling `yt_dlp.YoutubeDL(...).extract_info()` directly. All FastAPI requests queue behind the download.
**Why it happens:** yt-dlp is synchronous I/O. `async def` in FastAPI runs in the event loop thread.
**How to avoid:** Always wrap in `asyncio.to_thread()` or `loop.run_in_executor(None, ...)`.
**Warning signs:** Other API endpoints (e.g., /health) become unresponsive during a download.

### Pitfall 2: YouTube PO Token HTTP 403 in Server Environments
**What goes wrong:** yt-dlp returns HTTP 403 for YouTube URLs in containerized or headless environments. This is the P0 risk flagged in STATE.md.
**Why it happens:** YouTube requires a Proof of Origin (PO) Token generated by browser/client attestation. Server IPs lack this attestation.
**How to avoid:** Test with a real YouTube URL immediately (first working task). If 403 occurs, options are: (a) bgutil-ytdlp-pot-provider plugin, (b) YouTube cookies via `cookiefile` option, (c) use `--extractor-args "youtube:player_client=ios"` as a workaround (iOS client sometimes skips PO Token requirement).
**Warning signs:** `ERROR: [youtube] XYZ: HTTP Error 403: Forbidden` in yt-dlp output.
**Source:** https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide

### Pitfall 3: Wrong Output Filename After Merge
**What goes wrong:** `ydl.prepare_filename(info)` returns `.mp4` but actual file is `.mkv` (or vice versa) after ffmpeg merging. File not found when serving.
**Why it happens:** Known yt-dlp bug (issues #9030, #5517) — prepare_filename doesn't reflect postprocessor output extension.
**How to avoid:** Use UUID-prefix outtmpl + `glob.glob(f"{file_id}.*")` after download.
**Warning signs:** FileNotFoundError on `GET /files/{id}` immediately after a successful download.

### Pitfall 4: Playlist URL Accepted When Expecting Single Video
**What goes wrong:** YouTube playlist URL (`.../playlist?list=...`) triggers multi-video download, filling disk and taking minutes.
**Why it happens:** `noplaylist: True` stops the actual multi-download but `extract_info` may still return `_type: 'playlist'` metadata.
**How to avoid:** Check `_type` before download (SEC-02). `noplaylist: True` in opts as secondary guard.
**Warning signs:** Download takes >60 seconds; multiple files appear in downloads dir for one request.

### Pitfall 5: Scheduler Runs During Import / Tests
**What goes wrong:** Scheduler started at module level runs cleanup jobs during pytest collection, deletes test files, or causes errors when no event loop exists.
**How to avoid:** Always start scheduler inside lifespan context manager, never at module level.
**Warning signs:** Cleanup function called before any files are registered; test failures mentioning scheduler.

### Pitfall 6: Race Condition Between Cleanup and File Serving
**What goes wrong:** Cleanup thread deletes a file between `get_file()` check (record exists) and `FileResponse` read (file gone). Results in 500 error.
**Why it happens:** Two threads: BackgroundScheduler thread (cleanup) and uvicorn worker thread (request).
**How to avoid:** Use `threading.Lock` around all registry reads/writes. In the serve handler, catch `FileNotFoundError` and return 404 gracefully.

### Pitfall 7: env var API_KEY not set → empty string matches anything
**What goes wrong:** `os.environ.get("API_KEY", "")` returns `""` in dev. A request with `X-API-Key: ` (empty) would pass validation if the check is `key == API_KEY`.
**How to avoid:** Add guard: `if not API_KEY: raise RuntimeError("API_KEY env var not set")` at startup, or check `if not key or key != API_KEY`.

---

## Code Examples

Verified patterns from research:

### Full YoutubeDL options dict for a 720p download
```python
# Source: yt-dlp PyPI docs + community examples (MEDIUM confidence)
import yt_dlp, uuid, os

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp/downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

file_id = str(uuid.uuid4())

ydl_opts = {
    "format": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "outtmpl": os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s"),
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "merge_output_format": "mp4",  # Force mp4 container for compatibility
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(url, download=True)
    # info["title"], info["duration"] available here
```

### Finding the actual downloaded file
```python
import glob

matches = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_id}.*"))
if not matches:
    raise RuntimeError(f"Download completed but file not found for {file_id}")
actual_path = matches[0]
actual_filename = os.path.basename(actual_path)
```

### FileResponse for binary download
```python
# Source: https://fastapi.tiangolo.com/advanced/custom-response/
from fastapi.responses import FileResponse

@app.get("/files/{file_id}")
async def serve_file(file_id: str, key: str = Depends(verify_api_key)):
    record = get_file(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="File has expired")
    return FileResponse(
        path=record.path,
        filename=record.filename,         # Sets Content-Disposition: attachment; filename="..."
        media_type=record.content_type,
    )
```

### POST /download response model
```python
from pydantic import BaseModel
from datetime import datetime

class DownloadResponse(BaseModel):
    download_url: str    # e.g. "http://host/files/{file_id}"
    expires_at: datetime
    filename: str
    title: str
    duration: int        # seconds; from yt-dlp info["duration"]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@app.on_event("startup")` | `lifespan` context manager | FastAPI ~0.93 | on_event deprecated; lifespan is now standard |
| `loop.run_in_executor(None, fn)` | `asyncio.to_thread(fn)` | Python 3.9 | Cleaner syntax; same semantics |
| APScheduler v4 AsyncScheduler | APScheduler v3 BackgroundScheduler | v4 still in alpha (4.0.0a6) | Use v3 for production; v4 API is unstable |
| youtube-dl | yt-dlp | 2021 fork | yt-dlp is actively maintained; youtube-dl is dormant |

**Deprecated/outdated:**
- `@app.on_event("startup")` / `@app.on_event("shutdown")`: Deprecated in FastAPI. Use `lifespan` parameter instead.
- `youtube-dl`: Use `yt-dlp` (fork). youtube-dl has had multiple periods of no maintenance.
- `fastapi-slim`: No longer maintained. Use `fastapi[standard]` or `fastapi` directly.

---

## Open Questions

1. **YouTube PO Token behavior in this specific deployment**
   - What we know: PO Tokens required for some YouTube clients in server environments; HTTP 403 is the symptom.
   - What's unclear: Whether the specific Docker/Coolify environment triggers this; whether iOS client workaround (`player_client=ios`) is sufficient.
   - Recommendation: Make real YouTube URL download the FIRST manual test in Phase 1. If it fails with 403, implement cookie-based auth or bgutil plugin before proceeding.

2. **yt-dlp `_type` field reliability for playlist detection (SEC-02)**
   - What we know: `_type == "playlist"` is the documented check. Some sites (Twitter) have edge cases where single videos are misclassified.
   - What's unclear: Whether YouTube playlist URLs reliably return `_type == "playlist"` with `process=False`.
   - Recommendation: Test playlist detection with YouTube playlist URL specifically. Add `noplaylist: True` to download opts as belt-and-suspenders.

3. **`merge_output_format: "mp4"` vs letting yt-dlp choose container**
   - What we know: mp4 improves compatibility (especially for iOS in Phase 2+). mkv is more flexible.
   - What's unclear: Whether forcing mp4 causes issues with audio-only downloads or some codecs.
   - Recommendation: Use `merge_output_format: "mp4"` for video qualities; omit for `audio-only` (let yt-dlp pick m4a/webm).

---

## Sources

### Primary (HIGH confidence)
- https://pypi.org/project/fastapi/ — FastAPI 0.135.1, Python >=3.10 confirmed
- https://pypi.org/project/yt-dlp/ — yt-dlp 2026.3.3, Python 3.10+ confirmed
- https://pypi.org/project/APScheduler/ — APScheduler 3.11.2 production/stable; v4 still alpha
- https://fastapi.tiangolo.com/tutorial/handling-errors/ — Exception handler override patterns
- https://fastapi.tiangolo.com/advanced/custom-response/ — FileResponse parameters and usage
- https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide — PO Token requirements and workarounds

### Secondary (MEDIUM confidence)
- https://sentry.io/answers/schedule-tasks-with-fastapi/ — APScheduler + lifespan code example
- yt-dlp GitHub issues #9030, #5517 — prepare_filename() extension bug confirmed
- yt-dlp GitHub issue #9487 — ProcessPoolExecutor pickling error confirmed; ThreadPoolExecutor recommended
- https://apscheduler.readthedocs.io/en/3.x/ — IntervalTrigger, BackgroundScheduler docs

### Tertiary (LOW confidence — needs validation)
- yt-dlp `_type == "playlist"` check via `process=False` — documented in multiple community examples but not in official API docs; validate with real test
- iOS client workaround for PO Token (`player_client=ios`) — community-reported, not in official docs

---

## Metadata

**Confidence breakdown:**
- Standard stack (FastAPI, yt-dlp, APScheduler versions): HIGH — confirmed via PyPI
- Architecture patterns (lifespan, to_thread, FileResponse): HIGH — FastAPI official docs
- yt-dlp embedding patterns (format strings, UUID outtmpl): MEDIUM — community docs + GitHub issues
- Playlist detection (_type check): MEDIUM — community pattern, validated by multiple sources but official API not documented
- PO Token risk: HIGH (risk confirmed) / LOW (specific workaround effectiveness) — wiki confirmed, container behavior unconfirmed

**Research date:** 2026-03-09
**Valid until:** 2026-04-09 (30 days — yt-dlp updates frequently, verify version before install)
