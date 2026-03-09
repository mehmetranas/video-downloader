# Project Research Summary

**Project:** Video Downloader API (yt-dlp + FastAPI + Docker/Coolify)
**Domain:** Personal-use synchronous video download REST API for iOS Shortcuts integration
**Researched:** 2026-03-09
**Confidence:** MEDIUM-HIGH (stack HIGH, features HIGH, architecture MEDIUM, pitfalls MEDIUM)

## Executive Summary

This is a personal-use REST API that accepts a video URL, downloads it via yt-dlp, stores it temporarily, and returns a time-limited download URL. The canonical design is a synchronous FastAPI service: the POST /download endpoint blocks until the download completes and returns a JSON payload with the file URL and expiry timestamp. The caller (iOS Shortcut) then issues a GET /files/{id} request to retrieve the binary file. The entire architecture — in-memory file registry, asyncio background cleanup, container-local ephemeral storage — is sized correctly for a single user and should not be over-engineered toward queue-based or multi-user patterns.

The recommended stack is FastAPI 0.135.1 + yt-dlp (unpinned, always latest) + ffmpeg (system binary) + APScheduler 3.11.2, running in a `python:3.12-slim` Docker image. The key integration insight is that yt-dlp's Python class must be wrapped in `run_in_executor` to avoid blocking the async event loop, and ffmpeg must be present in the container as a hard dependency for any format beyond lowest-quality audio-only streams. No database, queue, or cache layer is needed — an in-memory dict with a threading.Lock is the right data store for this scope.

The primary risks are operational, not architectural. YouTube bot detection and yt-dlp version staleness require that yt-dlp is never version-pinned in the Dockerfile. The sync-download design creates a proxy timeout risk in Coolify's Traefik layer (default 60s kills long downloads) that must be configured explicitly. Disk exhaustion from partial `.part` files and orphaned downloads requires both registry-driven TTL cleanup and a filesystem sweep as a safety net. Security requires URL validation to prevent SSRF attacks via yt-dlp.

## Key Findings

### Recommended Stack

The stack is deliberately minimal. Python 3.12 + FastAPI provides async-capable routing with zero framework overhead. yt-dlp's Python class (`YoutubeDL`) is used directly — not as a subprocess — to get structured exception handling and typed option dicts. ffmpeg is installed as a system binary via apt (NOT the `ffmpeg-python` PyPI package, which is dead). APScheduler 3.x (not 4.x, which is still alpha) manages the cleanup job. The entire stack runs in a single uvicorn process — no gunicorn, no Celery, no Redis.

**Core technologies:**
- **Python 3.12 on `python:3.12-slim`**: stable runtime; slim not alpine — musl libc breaks yt-dlp C extension dependencies
- **FastAPI 0.135.1 + uvicorn 0.41.0**: async-native framework; uvicorn[standard] pulls in uvloop for Linux performance
- **yt-dlp (unpinned)**: always latest — YouTube changes bot detection weekly, pinning causes silent failures
- **ffmpeg (system binary via apt)**: hard dependency for 720p+, audio-only, and mp4 container remux
- **APScheduler 3.11.2**: background cleanup scheduler; 4.x is still alpha as of 2026
- **anyio + threading.Lock**: thread-safe in-memory file registry; no Redis or SQLite needed

### Expected Features

All table-stakes features are low-complexity due to yt-dlp's capabilities. The full v1 feature set is achievable in a single development phase. Differentiating features (metadata in response, filename sanitization, Content-Disposition headers) are nearly free — they piggyback on work already done during yt-dlp invocation.

**Must have (table stakes) — v1:**
- `POST /download` accepting `{url, quality}` — core service value
- Quality/format selection (`best`, `1080p`, `720p`, `480p`, `audio`) mapped to yt-dlp format strings
- `GET /files/{id}` file serving with correct Content-Type and Content-Disposition headers
- API key authentication via `X-API-Key` header
- 1-hour TTL with background cleanup preventing disk exhaustion
- Structured JSON error responses — iOS Shortcuts requires machine-readable errors
- `GET /health` endpoint for Coolify container readiness checks
- ffmpeg in Docker image for audio extraction and mp4 remux

**Should have (differentiators) — v1 bundled:**
- Metadata in response (`title`, `duration`, `filename`) — free from yt-dlp info dict
- Filename sanitization via yt-dlp outtmpl — human-readable names for iOS Files app
- Explicit `expires_at` ISO 8601 timestamp in response
- `mp4` container enforcement option — iOS Photos requires H.264/AAC in mp4

**Defer (v2+):**
- Platform-specific cookie injection for Instagram/Twitter (adds operational complexity)
- Richer metadata (`thumbnail_url`, `uploader`) — add when iOS Shortcut UI needs preview
- Configurable TTL via env var — only needed if 1 hour proves insufficient
- Audio format selection (mp3 vs m4a) as API parameter

**Explicitly rejected (anti-features):**
- Async download with job polling — iOS Shortcuts cannot implement polling loops
- Progress reporting via SSE/WebSocket — iOS Shortcuts does not support these protocols
- Playlist/batch download — unbounded disk usage, out of scope
- Multi-user key management — single deployment, single user

### Architecture Approach

The architecture is a single FastAPI process with four internal components: API key middleware, the download service (wraps yt-dlp in a thread pool), an in-memory file registry (UUID → file metadata with expiry), and an asyncio background cleanup task. All components communicate via direct Python method calls — no IPC, no message passing, no event system. The build order matters: config and auth first, then models, then registry, then download service and cleanup service (parallel), then routers, then the app entry point.

**Major components:**
1. **API Key Middleware** (`auth.py`) — `Depends(require_api_key)` using `secrets.compare_digest`; applied to all routes except `/health`
2. **Download Service** (`services/downloader.py`) — validates URL, builds yt-dlp opts, runs blocking download in thread pool via `run_in_executor`, registers result in FileRegistry
3. **File Registry** (`services/registry.py`) — in-memory dict with threading.Lock; maps UUID4 file_id to path + expires_at + filename; resets on restart (acceptable — ephemeral by design)
4. **Cleanup Scheduler** (`services/cleanup.py`) — asyncio background task started via FastAPI lifespan; runs every 5 minutes; registry-driven deletion + filesystem sweep for orphaned files
5. **File Server** (`routers/files.py`) — `FileResponse` with Content-Disposition; checks registry existence before serving; handles 404/410 for missing/expired files

### Critical Pitfalls

1. **Blocking the event loop with yt-dlp** — wrap ALL yt-dlp calls in `await loop.run_in_executor(None, blocking_fn)` or `starlette.concurrency.run_in_threadpool`; this is a Phase 1 architecture decision that cannot be retrofitted

2. **yt-dlp version staleness / YouTube bot detection** — never version-pin yt-dlp in Dockerfile (`pip install yt-dlp`, no version); propagate yt-dlp stderr to structured error responses; monitor for 0-byte downloads and "Sign in to confirm" errors

3. **Proxy timeout through Coolify/Traefik** — Traefik's default 60s proxy timeout kills downloads of videos longer than ~1 minute; configure explicit timeout middleware label (300s) in docker-compose before first Coolify deployment

4. **Disk exhaustion from partial files** — yt-dlp creates `.part` files that are never registered in the file registry; cleanup must include a filesystem sweep (delete any file older than 90 minutes regardless of registry state); use `--no-part` yt-dlp option if resumability is not needed

5. **SSRF via unvalidated URL input** — before passing any URL to yt-dlp, validate scheme is http/https, resolve hostname, and reject private/loopback IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16); return 422 on invalid URLs

## Implications for Roadmap

Based on research, the entire feature set is achievable in two phases: a core application phase and a deployment/hardening phase. The architecture has no complex dependencies that would require a 3+ phase split of core functionality.

### Phase 1: Core Application

**Rationale:** All application logic — download, serve, cleanup, auth — is tightly coupled through the FileRegistry. These components must be built and tested together. Splitting into sub-phases would require mocking the registry repeatedly. Research shows the build order within this phase: config/auth → models → registry → services → routers → main app.

**Delivers:** A fully functional Docker image that accepts POST /download, returns a time-limited URL, serves the file via GET /files/{id}, cleans up expired files automatically, and rejects unauthenticated requests.

**Addresses (from FEATURES.md):** All P1 must-have features — POST /download, quality selection, file serving, API key auth, TTL cleanup, structured errors, health check, metadata in response, filename sanitization.

**Avoids (from PITFALLS.md):**
- Event loop blocking: thread pool pattern baked in from first line of download logic
- Disk exhaustion: cleanup with filesystem sweep designed alongside registry
- SSRF: URL validation is the first thing the endpoint does
- Format string injection: quality param mapped to hardcoded format strings, never passed through
- Cleanup race condition: `os.path.exists` guard in file serve handler

### Phase 2: Docker and Deployment

**Rationale:** Dockerfile and Coolify configuration must be tested last — they depend on the complete application. Several pitfalls (proxy timeout, container storage strategy) only manifest through the actual Coolify proxy and only appear with a complete app to test with. The ARCHITECTURE.md build order explicitly places Dockerfile at step 8.

**Delivers:** A Coolify-deployable Docker image with correct proxy timeout configuration, environment variable setup, health check integration, and verified storage strategy.

**Uses (from STACK.md):** `python:3.12-slim`, system ffmpeg via apt, uvicorn CMD, environment variables `API_KEY`/`TEMP_DIR`/`TTL_HOURS`

**Avoids (from PITFALLS.md):**
- Proxy timeout: explicit Traefik timeout middleware configured in docker-compose
- Container ephemeral storage: volume strategy decided (container-local vs host volume vs tmpfs with size limit)
- yt-dlp version staleness: `pip install yt-dlp` with no version pin confirmed in Dockerfile

### Phase 3: v1.x Enhancements (post-validation)

**Rationale:** Research identifies three features as "add after validation" — mp4 container enforcement, richer metadata, configurable TTL. These should not block launch but are low-effort additions once the core is proven working in production.

**Delivers:** iOS compatibility hardening (mp4 enforcement), richer response metadata for Shortcut UX, operational tuning (configurable TTL, disk cap enforcement).

**Addresses (from FEATURES.md):** P2 features — mp4 container enforcement, `thumbnail_url`/`uploader` in response, `DOWNLOAD_DIR_MAX_BYTES` guard.

### Phase Ordering Rationale

- **Phase 1 before Phase 2** because Docker testing requires a working application to test with; debugging Traefik timeout issues with a partially implemented app wastes time
- **Single Phase 1 for all app logic** because the FileRegistry is shared by download, serve, and cleanup — building them in separate phases requires repeated mocking with no benefit at this project size
- **Phase 3 deferred** because mp4 enforcement and richer metadata cannot be validated as necessary until the core service is running against real iOS Shortcut usage; research explicitly marks these as "add when issues surface"

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (Coolify deployment):** Traefik timeout label syntax and current Coolify-bundled Traefik version should be verified against live Coolify documentation before writing docker-compose; training data confidence is MEDIUM on this specific syntax
- **Phase 2 (storage strategy):** The choice between container-local `/tmp/videos`, host-mounted volume, and `tmpfs` with size limit depends on the specific VPS disk configuration; verify available disk on target host before committing to storage approach

Phases with standard patterns (skip research-phase):
- **Phase 1 (Core Application):** All patterns are well-documented (FastAPI Depends, run_in_executor, FileResponse, asyncio lifespan tasks); no novel integrations; ARCHITECTURE.md provides working code examples for every component
- **Phase 3 (Enhancements):** mp4 container enforcement is a single yt-dlp option flag; richer metadata is reading additional keys from the already-populated info dict; no research needed

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Package versions verified against PyPI and GitHub Releases API; Docker patterns verified against known working community setups |
| Features | HIGH | yt-dlp inspected live at v2026.02.21; feature set derived directly from PROJECT.md and yt-dlp capabilities; iOS Shortcuts behavior is MEDIUM (training data) |
| Architecture | MEDIUM | Core patterns (Depends, run_in_executor, FileResponse, lifespan) are HIGH confidence; Coolify/Traefik integration is MEDIUM; code examples in ARCHITECTURE.md are unverified but represent standard patterns |
| Pitfalls | MEDIUM | Event loop, SSRF, disk exhaustion, and format injection are HIGH confidence (well-established); Traefik timeout configuration and YouTube PO token behavior are MEDIUM |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **iOS Shortcuts HTTP timeout:** The hardcoded iOS Shortcuts HTTP timeout value is unconfirmed. If it is shorter than 60-120s, the sync design breaks for large videos. Validate at integration time; add a size/duration guard in the download endpoint as a precaution.

- **Traefik timeout label syntax:** Exact syntax for Coolify's bundled Traefik version is unconfirmed. Verify against live Coolify documentation before writing production docker-compose. Have a fallback plan (e.g., direct Traefik configuration via Coolify dashboard).

- **YouTube PO token behavior:** As of late 2024, YouTube began requiring proof-of-origin tokens. Latest yt-dlp handles this transparently for many cases, but behavior in containerized environments with no browser cookies is not confirmed. Test with real YouTube URLs immediately in Phase 1 and treat this as a P0 verification step.

- **Instagram/Twitter cookie strategy:** The project scope includes these platforms but they require authenticated cookies. The v1 launch should treat these as best-effort and document that a cookie refresh procedure is needed for continued support.

## Sources

### Primary (HIGH confidence)
- yt-dlp v2026.02.21 live inspection — extractor count (1,872), format selection syntax, `--no-part`, outtmpl options
- yt-dlp GitHub Releases API — v2026.3.3 verified as latest release as of 2026-03-09
- PyPI index — FastAPI 0.135.1, uvicorn 0.41.0, APScheduler 3.11.2 version verification
- FastAPI documentation — `Depends()` pattern, `FileResponse`, lifespan context manager, `run_in_executor`
- PROJECT.md — authoritative scope: single user, iOS Shortcuts caller, sync design, Coolify deployment

### Secondary (MEDIUM confidence)
- yt-dlp README — ffmpeg hard dependency for stream merging documented
- Community patterns — python:3.12-slim vs alpine for C extension dependencies (well-documented issue)
- FastAPI community — APScheduler vs asyncio background task tradeoffs
- Coolify documentation (training data) — Dockerfile-based deployment, environment variable handling, Traefik proxy integration

### Tertiary (LOW confidence)
- iOS Shortcuts HTTP timeout limit — unverified; assumed ~60s based on general HTTP client patterns; validate at integration time
- Traefik timeout middleware label syntax for current Coolify-bundled version — verify against live docs before Phase 2

---
*Research completed: 2026-03-09*
*Ready for roadmap: yes*
