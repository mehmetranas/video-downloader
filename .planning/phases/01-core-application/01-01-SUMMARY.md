---
phase: 01-core-application
plan: 01
subsystem: api
tags: [fastapi, uvicorn, apscheduler, yt-dlp, python-dotenv, threading]

# Dependency graph
requires: []
provides:
  - FastAPI app with lifespan context manager
  - GET /health endpoint (no auth, returns {"status":"ok"})
  - X-API-Key authentication dependency (verify_api_key)
  - Structured JSON error handlers for all exception types
  - FileRecord dataclass (file_id, path, filename, title, duration, expires_at, content_type)
  - FileRegistry: module-level dict + threading.Lock, register_file(), get_file(), cleanup_expired()
  - APScheduler BackgroundScheduler running cleanup_expired every 5 minutes
  - QUALITY_MAP with 5 quality levels
  - Startup guard (RuntimeError if API_KEY not set)
  - requirements.txt, .env.example, .gitignore
affects: [02-core-application]

# Tech tracking
tech-stack:
  added:
    - fastapi[standard]==0.135.1
    - uvicorn[standard]
    - yt-dlp==2026.3.3
    - APScheduler==3.11.2
    - python-dotenv
    - python-multipart
  patterns:
    - FastAPI lifespan context manager (not deprecated @app.on_event)
    - APIKeyHeader + Security dependency for X-API-Key auth
    - threading.Lock around module-level dict for thread-safe registry
    - APScheduler BackgroundScheduler started in lifespan (never at module level)
    - Structured JSON error responses overriding StarletteHTTPException, RequestValidationError, Exception

key-files:
  created:
    - main.py
    - requirements.txt
    - .env.example
    - .gitignore
  modified: []

key-decisions:
  - "Single main.py file — all routes, models, registry in one file (locked user decision, no modular split)"
  - "APScheduler BackgroundScheduler (not AsyncIOScheduler) — runs in separate thread, safe for file I/O without blocking event loop"
  - "threading.Lock releases before os.remove to avoid holding lock during slow disk I/O"
  - "Startup guard raises RuntimeError if API_KEY is empty — prevents silent auth bypass"
  - "Error response shape: {error, status_code} for HTTP errors; {error, detail} for validation errors"

patterns-established:
  - "Pattern: All routes except /health use Depends(verify_api_key)"
  - "Pattern: cleanup_expired acquires lock to collect keys, releases before disk I/O"
  - "Pattern: uuid-based file_id as registry key (used in Plan 02 for UUID outtmpl)"

requirements-completed: [SEC-01, OPS-01, OPS-02, OPS-03]

# Metrics
duration: 3min
completed: 2026-03-09
---

# Phase 1 Plan 01: FastAPI App Foundation Summary

**Single-file FastAPI service scaffolded with X-API-Key auth, APScheduler cleanup scheduler, thread-safe FileRegistry, and structured JSON error handlers — ready for download logic in Plan 02**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-09T07:30:55Z
- **Completed:** 2026-03-09T07:33:55Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created requirements.txt pinning all 6 dependencies (fastapi 0.135.1, yt-dlp 2026.3.3, APScheduler 3.11.2)
- Built main.py with complete app foundation: health endpoint, auth dependency, error handlers, FileRegistry, scheduler
- Verified: GET /health returns 200 JSON, startup guard raises RuntimeError on missing API_KEY, cleanup_expired() safe to call on empty registry

## Task Commits

Each task was committed atomically:

1. **Task 1: Project files** - `9b01b88` (chore)
2. **Task 2: main.py app foundation** - `16b1a8a` (feat)

## Files Created/Modified

- `main.py` - FastAPI app: lifespan, health, auth dep, exception handlers, FileRecord, FileRegistry, APScheduler
- `requirements.txt` - Pinned Python dependencies (6 packages)
- `.env.example` - API_KEY and DOWNLOAD_DIR stubs with comments
- `.gitignore` - Excludes .env, downloads/, __pycache__, *.pyc, .venv/

## Decisions Made

- Used `BackgroundScheduler` (not `AsyncIOScheduler`) — runs in a separate thread so file I/O cleanup doesn't block the async event loop
- Lock is released before `os.remove()` in `cleanup_expired()` — avoids holding the lock during slow disk operations
- Error response shape settled: `{"error": str, "status_code": int}` for HTTP exceptions; `{"error": "Validation error", "detail": [...]}` for validation errors; `{"error": "Internal server error"}` (no detail) for generic exceptions
- Startup guard pattern: `if not API_KEY: raise RuntimeError(...)` — prevents the app from starting silently with empty-string auth that would accept any blank key

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Bash tool shell state resets between invocations — background server process started with `&` was killed when the next bash call ran. Worked around by writing PID to file and using single-command chains. No code changes needed.

## User Setup Required

None - no external service configuration required. Run `cp .env.example .env` and set `API_KEY=your-secret-key-here` to start.

## Next Phase Readiness

- App foundation is fully functional and tested
- Plan 02 adds POST /download and GET /files/{file_id} routes on top of this foundation
- The `verify_api_key` dependency is ready to be added to all Plan 02 routes via `Depends(verify_api_key)`
- P0 concern from STATE.md remains: YouTube PO Token behavior in containerized environments — treat first real YouTube URL test in Plan 02 as P0 verification

## Self-Check: PASSED

- FOUND: main.py
- FOUND: requirements.txt
- FOUND: .env.example
- FOUND: .gitignore
- FOUND: .planning/phases/01-core-application/01-01-SUMMARY.md
- FOUND commit: 9b01b88 (chore: project files)
- FOUND commit: 16b1a8a (feat: main.py app foundation)

---
*Phase: 01-core-application*
*Completed: 2026-03-09*
