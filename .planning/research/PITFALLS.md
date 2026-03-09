# Pitfalls Research

**Domain:** yt-dlp based video downloader REST API (FastAPI + Docker + Coolify)
**Researched:** 2026-03-09
**Confidence:** MEDIUM — based on training knowledge of yt-dlp, FastAPI, Docker internals; web research tools unavailable; flag for live validation before Phase 1

---

## Critical Pitfalls

### Pitfall 1: Blocking the FastAPI Event Loop with yt-dlp

**What goes wrong:**
Calling `yt_dlp.YoutubeDL().download(url)` directly inside an `async def` route handler blocks the entire asyncio event loop for the duration of the download (seconds to minutes). No other requests can be served during this time. A single 4-minute YouTube video download at 720p effectively takes the API offline for all concurrent callers.

**Why it happens:**
Developers see yt-dlp's Python API and assume `async def route()` + `yt_dlp.YoutubeDL().download()` is non-blocking because the function is async. It isn't. yt-dlp's download is synchronous I/O-bound and CPU-bound work. The asyncio event loop runs on a single OS thread — blocking that thread blocks everything.

**How to avoid:**
Wrap the yt-dlp call in `asyncio.get_event_loop().run_in_executor(None, blocking_download_fn)` or use FastAPI's `run_in_threadpool` from `starlette.concurrency`. The synchronous download runs in a thread pool worker, freeing the event loop. Alternatively, use `subprocess.run` via `asyncio.create_subprocess_exec` with `await proc.wait()` — this is non-blocking by design since subprocess execution is handled by the OS.

```python
# WRONG — blocks the event loop
@app.post("/download")
async def download(url: str):
    ydl.download([url])  # blocks entire server

# CORRECT — run in thread pool
from starlette.concurrency import run_in_threadpool

@app.post("/download")
async def download(url: str):
    result = await run_in_threadpool(blocking_ydl_download, url, options)
    return result
```

**Warning signs:**
- API responds to health checks but hangs on all other endpoints during a download
- `curl /health` times out while a download is in progress
- Single-worker uvicorn with no threadpool configuration

**Phase to address:**
Phase 1 (Core download endpoint) — architecture decision must be made before first line of download logic is written.

---

### Pitfall 2: YouTube Bot Detection Breaking Downloads Silently

**What goes wrong:**
YouTube (and increasingly Instagram) serves throttled, degraded, or blocked responses to requests that look like automated bots. yt-dlp may return a file that is corrupt, empty, or is actually an error page rendered as video. In other cases yt-dlp raises a specific error but the caller only catches generic exceptions and returns a 500 with no useful message.

**Why it happens:**
YouTube actively fingerprints HTTP clients. Containerized environments have no cookies, no browser fingerprint, and hit rate limits fast. As of late 2024, YouTube began requiring PO tokens (proof-of-origin tokens) for certain requests. yt-dlp updated extractor logic to handle this, but old pinned versions of yt-dlp in Docker images break silently when YouTube changes its extraction strategy.

**How to avoid:**
1. Never pin yt-dlp to a specific version in Dockerfile — use `pip install -U yt-dlp` or at minimum track latest minor. yt-dlp releases hotfixes for platform changes weekly.
2. Pass `--cookies-from-browser` or provide a `cookies.txt` file for Instagram and age-gated YouTube content. For a personal-use API, exporting browser cookies once and mounting them as a Docker volume secret is acceptable.
3. Set a `User-Agent` that matches a real browser in yt-dlp options.
4. Propagate yt-dlp's stderr output into the API error response — don't swallow it.
5. For YouTube specifically: monitor for `Sign in to confirm you're not a bot` in stderr output and surface it as a distinct `403 Bot Detection` error code.

**Warning signs:**
- Downloaded file is 0 bytes or under 10KB for a video URL
- yt-dlp exits with code 0 but file is actually an HTML error page
- `ERROR: [youtube] Video unavailable` in stderr
- Sudden failure of previously working URLs after yt-dlp hasn't been updated in weeks

**Phase to address:**
Phase 1 (Core download endpoint) — error classification and yt-dlp update strategy must be in the initial implementation, not retrofitted.

---

### Pitfall 3: Sync POST Endpoint Timeout for Long Downloads

**What goes wrong:**
The project explicitly chose synchronous downloads (POST waits, returns URL). For iOS Shortcuts, this means the HTTP request stays open for the entire download duration. A 1080p YouTube video can take 30-120 seconds. iOS Shortcuts has an HTTP timeout. Nginx reverse proxies (used by Coolify) have default `proxy_read_timeout` of 60 seconds. The request times out mid-download, but the download continues in the background — creating orphaned files and no response to the client.

**Why it happens:**
The sync-download design is correct for simplicity, but Coolify/Nginx's default proxy timeout is not tuned for long-running synchronous HTTP requests. Developers test locally (no proxy) and it works; in production through Coolify's Traefik/Nginx proxy, 60-second requests silently fail.

**How to avoid:**
1. Configure Coolify's proxy timeout via labels or environment. For Traefik (Coolify's default proxy): set `traefik.http.middlewares.your-service.forwardauth.trustForwardHeader=true` and add `traefik.http.routers.your-service.middlewares=...` with a timeout middleware set to 300 seconds.
2. Set uvicorn's `--timeout-keep-alive` appropriately.
3. Cap download quality and add yt-dlp `--socket-timeout 30` to prevent indefinite stalls.
4. Test with a known slow URL (a 20-minute 1080p video) through the actual Coolify proxy before declaring success.

**Warning signs:**
- Downloads work locally but produce 504 Gateway Timeout in Coolify
- File appears in `/tmp/videos` on the container but the API returned an error
- iOS Shortcut reports "The request timed out" for videos over ~2 minutes at high quality

**Phase to address:**
Phase 1 (Core download endpoint) + Phase 2 (Deployment/Docker) — timeout must be set at both the application layer and the infrastructure layer.

---

### Pitfall 4: Disk Exhaustion from Accumulating Temp Files

**What goes wrong:**
The TTL cleanup job (delete files after 1 hour) runs on a schedule, but the schedule has gaps. If 10 concurrent downloads start just before a cleanup cycle, all complete before cleanup runs, and a new batch starts — disk fills up between cycles. Additionally, failed or interrupted downloads leave partial `.part` files that yt-dlp creates during download. The cleanup job only deletes completed files; partial files accumulate indefinitely.

**Why it happens:**
1. Cleanup interval is too coarse (e.g., every 60 minutes instead of every 5).
2. The cleanup job only tracks files it knows about (entries in an in-memory dict), not orphaned files on disk.
3. yt-dlp `.part` files are created before the download completes, so they are never registered in the tracking dict.

**How to avoid:**
1. Run cleanup on a short interval (every 5-10 minutes), not every hour.
2. In addition to TTL-based cleanup, add a filesystem sweep: delete any file in the download directory older than 90 minutes, regardless of tracking state. This catches orphaned `.part` files, files from crashed workers, etc.
3. Set an explicit total disk usage cap: if `/tmp/videos` exceeds e.g. 2GB, reject new download requests with `507 Insufficient Storage` until cleanup runs.
4. Set yt-dlp's `--no-part` option to disable `.part` files if resumability is not needed.

**Warning signs:**
- `df -h` inside the container shows `/` filling up during load
- yt-dlp starts failing with `OSError: [Errno 28] No space left on device`
- Many `.part` files accumulating in the download directory after a load spike

**Phase to address:**
Phase 1 (Core download endpoint) — cleanup architecture must be designed alongside download logic, not added later.

---

### Pitfall 5: Docker Container Ephemeral Storage is Smaller Than Expected in Coolify

**What goes wrong:**
The project notes `/tmp/videos` as storage, implying container-local ephemeral storage. Docker containers on a Coolify host share the host's root filesystem. The host may have a small root partition (e.g., a VPS with 20GB total, mostly used by OS and other containers). A 1080p 20-minute video can be 500MB-2GB. Three simultaneous downloads can saturate the available disk, crashing not just this container but all containers on the host.

**Why it happens:**
Developers test on dev machines with large disks and never hit the limit. In production on a constrained VPS, the shared root filesystem fills up. Docker has no built-in mechanism to limit writable layer storage per container unless `--storage-opt size=...` is used (only available with overlay2 + special kernel options, not available on all VPS providers).

**How to avoid:**
1. Mount the download directory as a Docker volume (`-v /host/path/videos:/app/videos`) instead of writing to the container's writable layer. This makes storage usage explicit and monitorable on the host.
2. Add a `DOWNLOAD_DIR_MAX_BYTES` environment variable and enforce it in application logic before accepting a new download request.
3. In Coolify, configure a persistent volume for the download directory to separate download storage from the container's root filesystem.
4. Alternatively, use `tmpfs` mount with an explicit size limit: `--tmpfs /app/videos:size=1g` — this is RAM-backed, so cap accordingly.

**Warning signs:**
- Host's `df -h` shows root filesystem filling up over time
- Other Coolify-managed services start failing mysteriously (they're on the same host filesystem)
- `docker system df` shows large "writable layer" size for the download service container

**Phase to address:**
Phase 2 (Docker/Coolify deployment) — volume strategy must be in the Dockerfile and docker-compose before deploying to production.

---

### Pitfall 6: SSRF via Unvalidated URL Input

**What goes wrong:**
The `POST /download` endpoint accepts a URL. Without validation, an attacker (or mistake) can pass internal URLs: `http://169.254.169.254/` (AWS metadata service), `http://localhost:6379/` (Redis), `http://coolify-internal-service/api/key`. yt-dlp will attempt to fetch these URLs and may succeed, leaking internal credentials or enabling unauthorized access to host services.

**Why it happens:**
Developers focus on "validate that it's a video URL" but implement it as a weak regex check that doesn't block private IP ranges. yt-dlp's extractor system will try many things before giving up, including following redirects that may land on internal endpoints.

**How to avoid:**
1. Validate URL scheme is `http` or `https` only (block `file://`, `ftp://`, etc.).
2. Resolve the hostname before passing to yt-dlp and reject if it resolves to a private/loopback IP: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16`.
3. Maintain an allowlist of known-supported domains (YouTube, Twitter, Instagram, etc.) and reject anything else with a `422 Unprocessable Entity`.
4. Even for a personal API protected by an API key — this defense matters because the API key itself could be leaked from a Shortcut or config.

**Warning signs:**
- No URL validation in the download endpoint
- yt-dlp errors mentioning unexpected domains in logs
- API accessible over the internet without IP restriction

**Phase to address:**
Phase 1 (Core download endpoint) — URL validation must be the first thing the endpoint does, before any download logic.

---

### Pitfall 7: Cleanup Race Condition — Serving Files Already Deleted

**What goes wrong:**
The cleanup job deletes a file exactly as a client is downloading it via `GET /files/{id}`. The client started the request just before TTL expiry. The cleanup job checks TTL, sees it's expired, deletes the file. The file serve handler returns a 404 mid-stream or the FileResponse raises an exception after headers are already sent.

**Why it happens:**
Cleanup runs in a background asyncio task on the same thread. There is no locking between the "is TTL expired?" check and the file deletion. The file serve handler and the cleanup job can interleave.

**How to avoid:**
1. Use a soft-delete pattern: mark the record as "expired" in the in-memory tracking dict before deleting from disk. The file serve handler checks this flag and returns `410 Gone` immediately instead of opening the file.
2. Add a small grace period to deletion: if a file is "being served" (tracked via a semaphore or reference count), defer deletion until the serve completes.
3. For this project's scale (personal use, very low concurrency), the simplest fix is: check `os.path.exists(filepath)` just before opening in the serve handler and return `404` if missing. Not race-condition-proof but sufficient for single-user scale.

**Warning signs:**
- Intermittent 500 errors on `/files/{id}` for files that exist in the tracking dict
- `FileNotFoundError` exceptions in the serve handler logs
- Errors appearing only when cleanup job is actively running

**Phase to address:**
Phase 1 (Core download endpoint) — cleanup architecture design.

---

### Pitfall 8: Instagram and Twitter/X Auth Failures

**What goes wrong:**
Instagram requires authentication for most content (private accounts, Stories, Reels from private accounts). Without credentials, yt-dlp returns an authentication error. Twitter/X moved behind login walls for many video content types post-2023. Without valid cookies, downloads fail with "Login required" or return only preview-quality content.

**Why it happens:**
Developers test with public YouTube URLs during development. Instagram/Twitter failures only appear during integration testing with real content. The API returns a 500 instead of a useful `401 Authentication Required for this platform`.

**How to avoid:**
1. Handle yt-dlp authentication errors as a distinct error class, returning `401` or `422` with a descriptive message: `{"error": "platform_auth_required", "platform": "instagram"}`.
2. For Instagram: provide a `cookies.txt` mounted as a Docker secret/volume from a logged-in browser session. Update it periodically (session cookies expire).
3. For Twitter/X: same cookie approach. Consider that the project scope says "yt-dlp supported platforms" — document that Instagram/Twitter require periodic cookie refresh.
4. Never bake credentials or cookies directly into the Docker image — use environment variables or mounted files.

**Warning signs:**
- yt-dlp stderr contains `ERROR: This video is only available for registered users`
- Instagram downloads work for a week then start failing (cookies expired)
- No distinction in error responses between "URL not supported" and "auth required"

**Phase to address:**
Phase 1 (Core download endpoint) for error handling; Phase 2 (Docker deployment) for cookie injection strategy.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Calling yt-dlp as subprocess (CLI) instead of Python API | Simpler error handling, stdout capture, process isolation | Slightly more overhead per call; harder to configure | Acceptable — subprocess is actually safer (crash isolation) |
| In-memory dict for file tracking instead of SQLite | Zero dependencies, trivial code | Lost on container restart; no file recovery after crash | Acceptable for this project — personal use, TTL is short |
| Hardcoded cleanup interval (60s) | Simple timer | Cannot tune without code change | Acceptable, but make it an env var from day one |
| Single uvicorn worker | Simple | Blocks concurrent downloads (they queue on the thread pool) | Acceptable for personal single-user use; add worker count env var |
| No download progress reporting | Simpler API | iOS Shortcut cannot show progress | Acceptable given sync design |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| yt-dlp Python API | Reusing a single `YoutubeDL` instance across requests | Create a new instance per request — shared instances accumulate state and cookies between calls |
| yt-dlp Python API | Setting `outtmpl` to a fixed filename | Use `%(id)s.%(ext)s` with a unique subdirectory per request to prevent concurrent download filename collisions |
| FastAPI `FileResponse` | Serving from `/tmp` in read-only container | Ensure the container's `/tmp` or the mounted volume is writable by the app process user |
| Coolify Traefik proxy | No timeout configuration for long POST requests | Add `traefik.http.middlewares` with explicit timeout labels in docker-compose |
| yt-dlp `--format` selection | Passing user-provided format string directly | Map allowed quality values (`best`, `1080p`, `720p`, `480p`, `audio`) to hard-coded yt-dlp format strings — never pass user input directly to `--format` |
| Docker + yt-dlp | Installing yt-dlp via apt (often outdated) | Always install via `pip install yt-dlp` — apt packages lag weeks to months behind |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| No download concurrency limit | Memory and disk spike under rare concurrent use | Limit concurrent downloads via asyncio.Semaphore(N) where N=2-3 | Even at personal scale — iOS Shortcut retried requests can create 2-3 simultaneous downloads |
| yt-dlp downloading best-of-everything by default | Full 4K + lossless audio + all subtitles, multiple GB per download | Always specify explicit format string, not `bestvideo+bestaudio` without resolution cap | First time user requests a 4K video |
| Large file served via Python (FileResponse) | Memory pressure if files are large | FastAPI's FileResponse streams properly; but ensure Content-Length header is set so client can show progress | 1080p video > 500MB |
| Cleanup job accumulates dead tracking entries | Memory leak over days of operation | Prune expired entries from tracking dict during cleanup pass, not just from disk | Days of continuous operation |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Accepting arbitrary URLs without domain allowlist | SSRF — yt-dlp fetches internal services | Validate URL hostname resolves to public IP; maintain optional domain allowlist |
| Passing quality/format user input to yt-dlp format string | Format string injection — yt-dlp format strings support arbitrary field expressions | Map quality param to hard-coded format strings internally |
| API key in URL query parameter instead of header | Key appears in server access logs and iOS Shortcuts history | Always use `X-API-Key` header, never `?api_key=...` |
| Download directory accessible via path traversal in file ID | `GET /files/../../../etc/passwd` | Use UUID v4 as file ID and validate it matches `^[0-9a-f-]{36}$` before constructing path |
| Exposing yt-dlp version/platform in error messages | Reveals attack surface | Sanitize error messages before returning; log full errors internally |

---

## UX Pitfalls

(API-only service — UX = iOS Shortcut experience)

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Generic 500 error for all yt-dlp failures | Shortcut shows "Server Error" with no actionable info | Return structured errors with `error_code` field: `unsupported_url`, `bot_detection`, `auth_required`, `format_unavailable` |
| No `Content-Disposition` header on file download | iOS saves file as UUID with no extension | Set `Content-Disposition: attachment; filename="video-title.mp4"` on the file serve endpoint |
| No `Content-Type` header matching actual format | iOS cannot determine how to open the file | Set correct MIME type based on actual file extension after download completes |
| `expires_at` in epoch seconds instead of ISO 8601 | Shortcut date parsing requires extra steps | Return ISO 8601 UTC string: `2026-03-09T15:30:00Z` |
| Returning `download_url` as relative path | Shortcut must construct absolute URL | Return full absolute URL including scheme and host in the response |

---

## "Looks Done But Isn't" Checklist

- [ ] **TTL Cleanup:** Works in unit test but does it fire in Docker? Verify APScheduler/asyncio background task starts with the FastAPI lifespan, not just at import time.
- [ ] **File serving after cleanup:** The GET endpoint returns 200 in dev, but does it return proper 404/410 when the file has been cleaned up?
- [ ] **Concurrent download filenames:** Two requests for the same video URL — do they write to the same filename and corrupt each other?
- [ ] **yt-dlp errors surface to API:** A failed download returns 500 with stack trace instead of a structured error response.
- [ ] **Timeout through proxy:** POST /download tested locally (no proxy) but not through Coolify's Traefik. 60-second default kills long downloads.
- [ ] **Disk usage on host:** Container's download directory is growing the host root partition, not an isolated volume.
- [ ] **yt-dlp version in Docker image:** `docker build` caches the pip install layer — yt-dlp is pinned to the version at build time, not kept current.
- [ ] **Cookie expiry:** Instagram/Twitter cookies were valid at deploy time but expired 30 days later.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Event loop blocked (sync download in async) | HIGH | Refactor download call to threadpool; requires testing all error paths again |
| Disk exhaustion | LOW | SSH into host, `docker exec` into container, delete files, restart cleanup job |
| yt-dlp YouTube bot detection | LOW | `docker exec ... pip install -U yt-dlp` to update in running container; or redeploy |
| Proxy timeout (504s in production) | MEDIUM | Add Traefik timeout labels to docker-compose, redeploy via Coolify |
| Corrupt partial files accumulating | LOW | Add filesystem sweep to cleanup job; deploy update |
| Cleanup race condition serving deleted file | LOW | Add `os.path.exists` guard in serve handler; no data loss |
| SSRF (if exploited) | HIGH | Revoke API key immediately, audit yt-dlp fetch logs, add URL validation, redeploy |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Event loop blocked by yt-dlp | Phase 1: Core download endpoint | Load test: fire 3 concurrent downloads, confirm `/health` responds during all 3 |
| YouTube bot detection + silent errors | Phase 1: Core download endpoint | Test with real YouTube URL, verify structured error on failure |
| POST request timeout through proxy | Phase 1 + Phase 2: Docker/Coolify deployment | Test 5-minute download through Coolify proxy end-to-end |
| Disk exhaustion from partial files | Phase 1: Core download endpoint | Simulate failed download, verify `.part` file cleanup |
| Container ephemeral storage too small | Phase 2: Docker/Coolify deployment | Verify volume mount in docker-compose, test with large file |
| SSRF via URL input | Phase 1: Core download endpoint | Unit test with `http://169.254.169.254/`, `http://localhost/`, verify 422 response |
| Cleanup race condition | Phase 1: Core download endpoint | Unit test: delete file mid-serve, verify 404/410 not 500 |
| Instagram/Twitter auth failures | Phase 1: Core download endpoint | Test with Instagram URL, verify error code not generic 500 |
| format string injection | Phase 1: Core download endpoint | Unit test: pass `bestvideo[ext=webm]/worst` as quality param, verify it's rejected |
| Proxy timeout config | Phase 2: Docker/Coolify deployment | Deploy to Coolify, download a 10-minute video, verify no 504 |

---

## Sources

- yt-dlp GitHub repository (https://github.com/yt-dlp/yt-dlp) — issue tracker documents YouTube bot detection patterns and PO token requirements as of late 2024; extractor update frequency shows weekly releases for platform changes. MEDIUM confidence — training data verified against known release cadence.
- FastAPI documentation on async/sync — `run_in_threadpool` from `starlette.concurrency` is the documented pattern for running blocking code in async FastAPI routes. HIGH confidence — this is core FastAPI/Starlette design.
- Traefik proxy documentation — default read timeout behavior and how to configure it via Docker labels. MEDIUM confidence — training data, should be verified against current Coolify-bundled Traefik version.
- Docker documentation on container storage and writable layers — containers share host root filesystem by default, volumes isolate storage. HIGH confidence — core Docker behavior.
- SSRF attack patterns and private IP ranges — OWASP SSRF guidance. HIGH confidence — well-established security knowledge.
- yt-dlp `--no-part` flag and `outtmpl` patterns — yt-dlp CLI documentation. HIGH confidence — stable yt-dlp feature set.

---
*Pitfalls research for: yt-dlp video downloader API service (FastAPI + Docker + Coolify)*
*Researched: 2026-03-09*
