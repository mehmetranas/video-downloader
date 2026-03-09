---
phase: 01-core-application
plan: 02
subsystem: api
tags: [fastapi, yt-dlp, asyncio, fileresponse, pydantic, uuid]

# Dependency graph
requires:
  - phase: 01-core-application/01
    provides: FastAPI app foundation, FileRecord dataclass, FileRegistry, auth dependency, QUALITY_MAP, constants
provides:
  - POST /download route with playlist detection, async yt-dlp download, FileRegistry registration
  - GET /files/{file_id} route with 404/410/binary-serve logic
  - download_video() synchronous helper (UUID-prefixed outtmpl, glob-based file resolution)
  - _check_playlist() synchronous helper (yt-dlp extract_info, no download)
  - DownloadRequest and DownloadResponse Pydantic models
affects: [01-core-application/03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - asyncio.to_thread for all yt-dlp calls (both playlist check and download) — event loop never blocked
    - glob.glob for finding actual output file after yt-dlp postprocessing (extension may change)
    - UUID as file_id and outtmpl prefix — decouples registry key from filesystem filename
    - FileResponse with explicit filename and media_type for correct Content-Disposition header
    - Playlist check before download begins — fail fast with 422 before starting expensive operation

key-files:
  created:
    - test_task2.py
  modified:
    - main.py

key-decisions:
  - "asyncio.to_thread used for both _check_playlist and download_video — ensures yt-dlp I/O never blocks the event loop"
  - "glob-based file resolution after download — handles yt-dlp postprocessor extension changes (e.g., .webm -> .mp4 after merge)"
  - "content_type: audio/mp4 for audio-only, video/mp4 for all video qualities — simple mapping, not sniffed from actual file"
  - "download_url constructed as str(request.base_url) + files/{file_id} — uses request base URL to support any host/port"
  - "noplaylist=True as belt-and-suspenders on yt-dlp options even though playlist check runs first"

patterns-established:
  - "Pattern: All blocking I/O (yt-dlp) wrapped in asyncio.to_thread, never awaited directly from sync context"
  - "Pattern: UUID file_id as both registry key and outtmpl prefix — glob resolves actual path after download"
  - "Pattern: Playlist guard before expensive download — 422 returned before yt-dlp spawns any work"

requirements-completed: [DL-01, DL-02, FILE-01, FILE-02, SEC-02]

# Metrics
duration: 7min
completed: 2026-03-09
---

# Phase 1 Plan 02: Download Routes Summary

**POST /download and GET /files/{file_id} implemented — full request lifecycle from playlist guard to async yt-dlp download to UUID-based FileRegistry registration to binary FileResponse serving**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-09T11:36:47Z
- **Completed:** 2026-03-09T11:44:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Task 1 (Pydantic models + `_check_playlist`) was pre-built and committed in commit `32c2b7c` before this plan run
- Implemented `download_video()` synchronous helper with UUID-prefixed outtmpl and glob-based output file resolution
- Implemented POST /download with playlist guard (asyncio.to_thread), async download (asyncio.to_thread), and FileRegistry registration
- Implemented GET /files/{file_id} with 404 (missing), 410 (expired), 404 (missing on disk), and FileResponse for valid files
- 8 TDD tests all pass; smoke test confirms 401 on missing auth, 404 on missing file ID

## Task Commits

Each task was committed atomically:

1. **Task 1: Pydantic models + _check_playlist** - `32c2b7c` (feat) — pre-built before plan run
2. **Task 2: POST /download and GET /files/{file_id} routes** - `f999fd7` (feat)

## Files Created/Modified

- `main.py` - Added download_video(), POST /download, GET /files/{file_id}; moved asyncio import to top-level imports
- `test_task2.py` - TDD RED tests for Task 2 (8 tests, all passing after implementation)

## Decisions Made

- Used `asyncio.to_thread` for both `_check_playlist` and `download_video` — yt-dlp is synchronous and I/O-heavy; blocking the event loop would stall all concurrent requests
- Glob-based file resolution (`glob.glob(DOWNLOAD_DIR/{file_id}.*)`): yt-dlp postprocessors can rename the output file (e.g., merging video+audio streams changes extension), so the outtmpl pattern alone is not sufficient to find the actual output
- `content_type` set to `audio/mp4` for audio-only, `video/mp4` for all video qualities — simple deterministic mapping rather than sniffing the actual file bytes
- `download_url` built as `str(request.base_url) + f"files/{file_id}"` — uses FastAPI's `Request.base_url` so it works on any host, port, or reverse proxy prefix
- `noplaylist=True` added to yt-dlp options as belt-and-suspenders even though `_check_playlist` runs first — defense in depth against edge cases where yt-dlp silently expands a playlist

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `import asyncio` was initially added inline in the routes section (before the `@app.post` decorator). Fixed by moving it to the top-level stdlib imports block where it belongs. No functional impact.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- POST /download and GET /files/{file_id} are fully functional
- Plan 03 (checkpoint) will run a real YouTube URL download to verify yt-dlp behavior in the target environment and confirm the PO Token concern from STATE.md
- Content-Disposition header is set via `FileResponse(filename=...)` — browsers will receive it correctly

## Self-Check: PASSED

- FOUND: main.py (modified)
- FOUND: test_task2.py (created)
- FOUND commit: 32c2b7c (Task 1 — pre-built)
- FOUND commit: f999fd7 (Task 2 — routes implementation)

---
*Phase: 01-core-application*
*Completed: 2026-03-09*
