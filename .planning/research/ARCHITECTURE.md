# Architecture Research

**Domain:** yt-dlp based video downloader REST API (sync, personal use, Coolify/Docker)
**Researched:** 2026-03-09
**Confidence:** MEDIUM (training data; WebSearch/WebFetch unavailable for live verification)

---

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        HTTP Request Layer                        │
│                                                                  │
│   iOS Shortcut / curl / any HTTP client                         │
│        POST /download              GET /files/{file_id}         │
└────────────────────────┬───────────────────┬────────────────────┘
                         │                   │
┌────────────────────────▼───────────────────▼────────────────────┐
│                      FastAPI Application                         │
│                                                                  │
│  ┌──────────────────┐   ┌──────────────────┐                    │
│  │  API Key          │   │  Request Router   │                   │
│  │  Middleware       ├──►│  /download        │                   │
│  │  (X-API-Key       │   │  /files/{id}      │                   │
│  │   header check)   │   │  /health          │                   │
│  └──────────────────┘   └────────┬─────────┘                    │
│                                  │                               │
│  ┌───────────────────────────────▼────────────────────────────┐ │
│  │                    Download Service                         │ │
│  │                                                             │ │
│  │  1. Validate URL + quality param                            │ │
│  │  2. Generate unique file_id (UUID4)                         │ │
│  │  3. Call yt-dlp (blocking, run_in_executor)                 │ │
│  │  4. Register file in FileRegistry with expiry               │ │
│  │  5. Return {download_url, expires_at, filename, file_size}  │ │
│  └──────────────────────────────┬──────────────────────────────┘ │
│                                 │                                │
│  ┌───────────────────────────── ▼────────────────────────────┐  │
│  │                    File Registry                            │  │
│  │   (in-memory dict: file_id → {path, expires_at, filename}) │  │
│  └──────────────────────────────┬───────────────────────────┘  │
│                                 │                               │
│  ┌──────────────────────────────▼───────────────────────────┐  │
│  │                  Cleanup Scheduler                         │  │
│  │   (APScheduler or asyncio periodic task — every 5 min)    │  │
│  │   Scans registry, deletes expired files, removes entries   │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                   Local Temp Storage                             │
│                   /tmp/videos/                                   │
│                   {file_id}.mp4 (or .webm, .m4a etc.)           │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| API Key Middleware | Validate `X-API-Key` header on every protected route; return 401 if missing/wrong | FastAPI `Depends()` dependency injection or Starlette middleware |
| Request Router | Route HTTP verbs to handler functions; input validation via Pydantic models | FastAPI `@app.post`, `@app.get` decorators |
| Download Service | Orchestrate the full download: validate, invoke yt-dlp, persist metadata | Plain Python class/module; no ORM needed |
| yt-dlp Invoker | Call yt-dlp as a Python library (not subprocess) with YoutubeDL context manager | `yt_dlp.YoutubeDL(opts)` with `download([url])` |
| File Registry | Track live files: file_id → path, expires_at, original_filename | Python dict wrapped in a simple class; no DB needed at this scale |
| Cleanup Scheduler | Periodically delete expired files from disk and registry | `asyncio` background task started at app startup via `lifespan` |
| File Server | Serve binary file for GET /files/{id}; stream to client | `fastapi.responses.FileResponse` with appropriate Content-Disposition header |

---

## Recommended Project Structure

```
video-downloader/
├── app/
│   ├── main.py              # FastAPI app, lifespan, router registration
│   ├── config.py            # Settings via pydantic-settings (env vars)
│   ├── auth.py              # API key dependency (Depends)
│   ├── routers/
│   │   ├── download.py      # POST /download handler
│   │   └── files.py         # GET /files/{file_id} handler
│   ├── services/
│   │   ├── downloader.py    # yt-dlp invocation logic
│   │   ├── registry.py      # FileRegistry: in-memory file tracking
│   │   └── cleanup.py       # Periodic cleanup task
│   └── models.py            # Pydantic request/response models
├── Dockerfile
├── docker-compose.yml       # For local dev only
├── requirements.txt
├── .env.example
└── tests/
    ├── test_download.py
    ├── test_cleanup.py
    └── test_auth.py
```

### Structure Rationale

- **app/routers/:** Thin HTTP handlers only — extract URL, call service, return response. No business logic here.
- **app/services/:** All business logic lives here. Downloader and registry are separate concerns even though they interact — this keeps yt-dlp details isolated.
- **app/config.py:** Single source of truth for `API_KEY`, `TEMP_DIR`, `FILE_TTL_SECONDS`, `MAX_FILESIZE_MB`. Loaded once at startup.
- **Single flat registry:** At personal-use scale, an in-memory dict is correct. A database (SQLite, Redis) adds operational complexity with no benefit when there is one user and files last 1 hour.

---

## Architectural Patterns

### Pattern 1: Sync Download via run_in_executor

**What:** yt-dlp's `YoutubeDL.download()` is blocking CPU/IO work. In an async FastAPI handler, calling it directly blocks the event loop, making the API unresponsive to health checks or concurrent requests during a download. Wrapping it in `loop.run_in_executor(None, ...)` moves it to a thread pool without changing the caller's behavior — the POST still waits and returns the result.

**When to use:** Any blocking library call inside an async FastAPI route. This is the canonical pattern for yt-dlp specifically.

**Trade-offs:** Simple to implement; thread pool is already managed by Python. Downside: no per-request cancellation if the client disconnects — yt-dlp keeps running. At personal use scale this is acceptable.

**Example:**
```python
import asyncio
from yt_dlp import YoutubeDL

async def download_video(url: str, quality: str, output_path: str) -> str:
    ydl_opts = {
        "format": _quality_to_format(quality),
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
    }
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _blocking_download, ydl_opts, url)
    return output_path

def _blocking_download(opts: dict, url: str) -> None:
    with YoutubeDL(opts) as ydl:
        ydl.download([url])
```

### Pattern 2: In-Memory File Registry with TTL

**What:** A simple Python class wraps a dict mapping `file_id` (UUID4 string) to a metadata record. Every registered file has an `expires_at` timestamp. The cleanup job queries this registry, not the filesystem, for what to delete.

**When to use:** Whenever there is no need for persistence across restarts (files on disk are lost on restart anyway, so registry consistency is irrelevant on container restart).

**Trade-offs:** Zero dependencies, zero latency. Lost on restart — acceptable because temp files are also lost on restart. No concurrent write safety needed at single-user scale; a threading.Lock is still a good habit.

**Example:**
```python
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

@dataclass
class FileRecord:
    path: Path
    filename: str
    expires_at: datetime

class FileRegistry:
    def __init__(self, ttl_seconds: int = 3600):
        self._store: dict[str, FileRecord] = {}
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds

    def register(self, path: Path, filename: str) -> str:
        file_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        with self._lock:
            self._store[file_id] = FileRecord(path=path, filename=filename, expires_at=expires_at)
        return file_id

    def get(self, file_id: str) -> FileRecord | None:
        with self._lock:
            return self._store.get(file_id)

    def expire_all(self) -> list[FileRecord]:
        now = datetime.now(timezone.utc)
        expired = []
        with self._lock:
            expired_ids = [k for k, v in self._store.items() if v.expires_at <= now]
            for k in expired_ids:
                expired.append(self._store.pop(k))
        return expired
```

### Pattern 3: asyncio Lifespan Cleanup Task

**What:** FastAPI's `lifespan` context manager (preferred over deprecated `on_event`) starts a background `asyncio` task at app startup. The task runs an infinite loop with a `asyncio.sleep(interval)` between cleanup passes. On shutdown, the lifespan context cancels the task.

**When to use:** Always for periodic background work in FastAPI. APScheduler is an alternative but adds a dependency; asyncio task is sufficient for a single interval job.

**Trade-offs:** Simple, no extra packages. Does not survive container crashes mid-cleanup — files may linger until next cleanup pass. This is a non-issue for a 1-hour TTL with 5-minute cleanup intervals.

**Example:**
```python
from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup_loop(registry, interval_seconds=300))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

async def cleanup_loop(registry: FileRegistry, interval_seconds: int):
    while True:
        await asyncio.sleep(interval_seconds)
        expired = registry.expire_all()
        for record in expired:
            record.path.unlink(missing_ok=True)

app = FastAPI(lifespan=lifespan)
```

### Pattern 4: FileResponse for File Serving

**What:** `fastapi.responses.FileResponse` streams a file from disk to the client. It handles `Content-Length`, `Content-Type` detection, and `Range` requests automatically. Setting `filename` parameter sets `Content-Disposition: attachment` so browsers and iOS download it correctly.

**When to use:** Serving files from disk in FastAPI — this is the native solution. Do not read the file into memory first.

**Trade-offs:** File stays on disk until response is complete; cleanup must not delete a file while it is being served. The registry TTL (1 hour) and cleanup interval (5 min) make the window for this race negligible at personal scale.

**Example:**
```python
from fastapi import HTTPException
from fastapi.responses import FileResponse

@router.get("/files/{file_id}")
async def serve_file(file_id: str, auth: None = Depends(require_api_key)):
    record = registry.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found or expired")
    if not record.path.exists():
        raise HTTPException(status_code=410, detail="File has been deleted")
    return FileResponse(
        path=record.path,
        filename=record.filename,
        media_type="application/octet-stream",
    )
```

### Pattern 5: API Key as FastAPI Dependency

**What:** A single `Depends(require_api_key)` function reads `X-API-Key` from request headers, compares with env-configured key using `secrets.compare_digest` (timing-safe), and raises `HTTPException(401)` on mismatch. Applied to all routes except `/health`.

**When to use:** Single static API key — this is the right pattern. Do not use HTTP Basic Auth (wrong semantic), do not use Bearer token (overkill for static key).

**Trade-offs:** Zero overhead. Timing-safe comparison prevents timing attacks (good habit even on personal services).

**Example:**
```python
import secrets
from fastapi import Header, HTTPException, Depends
from app.config import settings

async def require_api_key(x_api_key: str = Header(...)):
    if not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
```

---

## Data Flow

### POST /download Request Flow

```
iOS Shortcut
    │  POST /download
    │  X-API-Key: <key>
    │  Body: {"url": "https://...", "quality": "720p"}
    ▼
FastAPI Middleware
    │  → require_api_key() validates X-API-Key header
    │  → 401 if invalid, continues if valid
    ▼
DownloadRouter.post_download()
    │  → Pydantic validates request body (url: HttpUrl, quality: Enum)
    │  → calls DownloadService.download(url, quality)
    ▼
DownloadService.download()
    │  → generates file_id = uuid4()
    │  → builds output_path = /tmp/videos/{file_id}.%(ext)s
    │  → await loop.run_in_executor(None, yt_dlp_download, opts, url)
    │     [blocks thread, not event loop — may take 5-60 seconds]
    │  → resolves actual output filename from disk (ext varies by format)
    │  → registry.register(path, filename, file_id)
    ▼
DownloadRouter
    │  → returns JSON:
    │    {
    │      "download_url": "https://host/files/{file_id}",
    │      "expires_at": "2026-03-09T15:00:00Z",
    │      "filename": "video_title.mp4",
    │      "file_size": 52428800
    │    }
    ▼
iOS Shortcut
    │  → parses JSON, extracts download_url
    │  → GET /files/{file_id} to download binary
    │  → saves to Photos / Files app
```

### GET /files/{file_id} Flow

```
iOS Shortcut
    │  GET /files/{file_id}
    │  X-API-Key: <key>
    ▼
FastAPI
    │  → require_api_key validates header
    │  → registry.get(file_id) → FileRecord or None
    │  → 404 if not in registry (expired or never existed)
    │  → FileResponse streams file from /tmp/videos/{file_id}.ext
    ▼
iOS Shortcut
    │  receives binary file
    │  saves to device
```

### Cleanup Flow (background, every 5 min)

```
asyncio cleanup_loop (background task)
    │  await asyncio.sleep(300)
    │  expired = registry.expire_all()
    │    → finds all records where expires_at <= now
    │    → removes them from registry dict
    │    → returns list of FileRecord
    │  for record in expired:
    │    → record.path.unlink(missing_ok=True)
    │  loops back to sleep
```

---

## Docker Container Structure

### Dockerfile Pattern (Coolify compatible)

```
FROM python:3.12-slim

# yt-dlp also needs ffmpeg for post-processing (merging audio+video streams)
# This is a critical system dependency
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Temp storage dir — container-local, intentionally ephemeral
RUN mkdir -p /tmp/videos

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Critical Docker Decisions

| Decision | Rationale |
|----------|-----------|
| `python:3.12-slim` not `alpine` | yt-dlp and many dependencies have C extensions; alpine's musl libc causes build failures for several packages |
| ffmpeg in image | yt-dlp downloads video and audio as separate streams for 720p+ from YouTube, then merges via ffmpeg. Without ffmpeg, best quality formats fail |
| `/tmp/videos` inside container | Intentionally ephemeral. No volume mount needed. Container restart = clean slate. This is correct for this use case |
| No non-root user in CMD | Optional security hardening; skip for personal use unless security posture demands it |
| Single CMD process (uvicorn) | No supervisor needed. One process, one concern. Coolify restarts the container if it crashes |

### Coolify Deployment Notes

Coolify requires only:
1. A `Dockerfile` at repo root (or configurable path)
2. `PORT` env var or `EXPOSE` in Dockerfile — Coolify reads `EXPOSE 8000`
3. Environment variables set in Coolify UI: `API_KEY`, `FILE_TTL_SECONDS` (optional, default 3600), `TEMP_DIR` (optional, default `/tmp/videos`)

No `docker-compose.yml` is needed for Coolify production deployment — compose is for local dev only.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| yt-dlp | Python library import (`yt_dlp.YoutubeDL`), not subprocess | Library mode gives structured errors vs. parsing stderr. Confidence: HIGH |
| ffmpeg | yt-dlp calls ffmpeg internally as a subprocess | Must be on PATH inside container. No direct app integration needed |
| Platform sites (YouTube, Instagram, X) | yt-dlp handles all HTTP to platforms | App never touches platform APIs directly |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Router → DownloadService | Direct function call (same process) | No queue, no IPC — sync is correct here |
| DownloadService → FileRegistry | Direct method call | Registry is a singleton injected at startup via FastAPI state or module-level instance |
| FileRegistry → CleanupTask | CleanupTask calls `registry.expire_all()` | CleanupTask holds a reference to the registry; no event system needed |
| FileRegistry → Router (file serving) | Router calls `registry.get(file_id)` | Same pattern — direct call |

---

## Anti-Patterns

### Anti-Pattern 1: Calling yt-dlp as a subprocess

**What people do:** `subprocess.run(["yt-dlp", url, "-o", path])` — treating yt-dlp as a CLI tool from within Python.

**Why it's wrong:** Subprocess loses structured error information (you parse stderr strings). Harder to set per-download options. yt-dlp is a Python library — use it as one. Subprocess also requires yt-dlp to be installed system-wide in PATH, creating a hidden dependency.

**Do this instead:** Import `yt_dlp` and use `YoutubeDL(opts)` context manager. Errors surface as exceptions, options are typed dicts, and the library is declared in `requirements.txt`.

### Anti-Pattern 2: Blocking the Event Loop

**What people do:** Call `yt_dlp.YoutubeDL(...).download([url])` directly inside an `async def` route handler.

**Why it's wrong:** yt-dlp download is blocking IO + CPU. It holds the event loop thread, preventing FastAPI from processing any other requests (including `/health`) during the entire download duration (5-60+ seconds).

**Do this instead:** `await asyncio.get_event_loop().run_in_executor(None, blocking_fn, args)` to offload to a thread pool thread.

### Anti-Pattern 3: Storing File Paths as Download URLs

**What people do:** Return the actual filesystem path or a direct static file mount as the download URL, exposing internal path structure.

**Why it's wrong:** Leaks internal file layout. No way to enforce expiry at the URL level. No way to validate the API key on file retrieval.

**Do this instead:** Return `/files/{uuid}` — the UUID is opaque, expiry is enforced by the registry lookup, and the route goes through API key middleware.

### Anti-Pattern 4: Using a Persistent Volume for Temp Files

**What people do:** Mount a Docker volume to `/tmp/videos` to persist files across restarts.

**Why it's wrong:** The files are supposed to be ephemeral (1-hour TTL). Persisting them across restarts creates orphaned files that the in-memory registry no longer knows about. The registry resets on restart, so the volume accumulates files that can never be served or cleaned up.

**Do this instead:** Keep temp files inside the container at `/tmp/videos`. On restart, both the registry and the files reset together — consistent state guaranteed.

### Anti-Pattern 5: Running Cleanup via Cron/External Scheduler

**What people do:** Add a cron job (in crontab or a separate container) to `find /tmp/videos -mmin +60 -delete`.

**Why it's wrong:** Filesystem-only cleanup is inconsistent with the in-memory registry. A file could still be in the registry (serveable) but deleted by cron. Or a file could be deleted while actively being downloaded by a client.

**Do this instead:** Registry-driven cleanup via the asyncio background task. The registry is the source of truth; filesystem changes follow from registry changes.

---

## Scaling Considerations

This is a personal-use service. Scaling to 10K+ is explicitly out of scope. But understanding where the constraints are informs design decisions.

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1 user (target) | Current architecture is correct. In-memory registry, sync download in thread pool, container-local storage. |
| 5-10 concurrent users | Add thread pool size limit to avoid 10 parallel yt-dlp processes overwhelming disk/network. `ThreadPoolExecutor(max_workers=3)` passed to `run_in_executor`. |
| 50+ users | In-memory registry becomes a scaling bottleneck (lost on restart, single-process). Replace with Redis. Move to async job queue (Celery/ARQ). Use object storage (S3) instead of local disk. This is a significant rearchitect. |

For this project, target is 1 user. Do not over-engineer toward 50+ user patterns.

---

## Suggested Build Order

Dependencies between components determine build order:

1. **Config + Auth** — Everything depends on settings loading and API key validation. Build first.
   - `config.py` (pydantic-settings, reads env vars)
   - `auth.py` (require_api_key dependency)

2. **Models** — Request/response Pydantic models. No dependencies.
   - `models.py` (DownloadRequest, DownloadResponse)

3. **File Registry** — Needed by both Download Service and Cleanup. Build before either.
   - `services/registry.py` (FileRegistry class)

4. **Download Service** — Depends on registry. Core business logic.
   - `services/downloader.py` (yt-dlp invocation, run_in_executor pattern)

5. **Cleanup Service** — Depends on registry. Can be built in parallel with Download Service.
   - `services/cleanup.py` (cleanup_loop coroutine)

6. **Routers** — Depend on all services. Thin HTTP layer.
   - `routers/download.py` (POST /download)
   - `routers/files.py` (GET /files/{id})

7. **App entry point** — Depends on all routers and lifespan.
   - `main.py` (FastAPI app, lifespan with cleanup task, router registration)

8. **Dockerfile** — Can be written anytime but tested last.
   - Verify ffmpeg present, yt-dlp installs cleanly, app starts.

---

## Sources

- yt-dlp Python library usage: training data (MEDIUM confidence) — verify against `yt-dlp` PyPI docs and README for current `YoutubeDL` option names
- FastAPI BackgroundTasks vs lifespan: training data (MEDIUM confidence) — lifespan is the current recommended pattern as of FastAPI 0.93+; `on_event` is deprecated
- FastAPI Depends pattern for auth: training data (HIGH confidence) — foundational FastAPI pattern, stable across versions
- FileResponse in FastAPI: training data (HIGH confidence) — documented in FastAPI docs, stable API
- asyncio.run_in_executor for blocking calls: training data (HIGH confidence) — standard Python asyncio pattern
- Docker python:3.12-slim vs alpine for yt-dlp: training data (MEDIUM confidence) — alpine musl issues with C extensions are well-documented community knowledge
- ffmpeg requirement for yt-dlp: training data (HIGH confidence) — yt-dlp README explicitly states ffmpeg is required for merging streams
- Coolify Dockerfile-based deployment: training data (MEDIUM confidence) — verify current Coolify docs for environment variable handling

---

*Architecture research for: yt-dlp video downloader REST API (FastAPI, Docker, Coolify)*
*Researched: 2026-03-09*
