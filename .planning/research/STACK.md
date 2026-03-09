# Stack Research: Video Downloader API

**Project:** Video Downloader API (yt-dlp + FastAPI + Docker/Coolify)
**Researched:** 2026-03-09
**Confidence:** HIGH — versions verified against PyPI and GitHub Releases API

---

## Core Stack

### Python Runtime
- **Python 3.12** — stable, well-supported, good async performance
- Docker base image: `python:3.12-slim` (NOT alpine — yt-dlp C extension deps fail on musl libc)

### Web Framework
- **FastAPI 0.135.1** — async-native, automatic OpenAPI docs, `Depends()` for API key middleware
- **uvicorn 0.41.0** (`uvicorn[standard]`) — pulls in uvloop for Linux containers, better event loop performance
- Do NOT use gunicorn — creates multiple scheduler processes, conflicts with single-instance design

### Video Download
- **yt-dlp 2026.3.3** (calver, released 2026-03-03) — use `YoutubeDL` Python class directly, NOT subprocess
- Never pin yt-dlp version in Docker — YouTube changes bot detection frequently, always install latest (`pip install yt-dlp`)
- **ffmpeg** — system binary installed via apt in Dockerfile (NOT `ffmpeg-python` PyPI package — last release 2020, dead)
- ffmpeg is a HARD DEPENDENCY for: YouTube 720p+ (separate video/audio streams), audio-only extraction, mp4 remux

### Async Handling
- `anyio.to_thread.run_sync()` — run blocking yt-dlp calls in thread pool without blocking event loop
- Do NOT call `YoutubeDL.download()` directly in `async def` routes — freezes entire server for download duration

### TTL Cleanup
- **APScheduler 3.11.2** — APScheduler 4.x is still alpha, use 3.x
- `AsyncIOScheduler` registered on FastAPI lifespan event
- Filesystem `mtime` as TTL record — no database needed
- Cleanup runs every N minutes, deletes files older than 1 hour

### File Registry
- In-memory Python dict with `threading.Lock` — keyed by UUID4
- Tracks: `{file_id: {path, expires_at, filename, size}}`
- Resets on container restart (acceptable — temp files also lost on restart)
- No Redis, no Celery, no SQLite needed

### API Authentication
- Single static API key via `X-API-Key` header
- FastAPI `Depends()` middleware — applied to all protected routes
- Key loaded from environment variable `API_KEY`

---

## What NOT To Use

| Library | Reason |
|---------|--------|
| `ffmpeg-python` | Dead package, last release 2020 — use system ffmpeg binary |
| `celery` + `redis` | Over-engineered for single-user sync API |
| `sqlite` / any DB | Filesystem mtime + in-memory dict is sufficient |
| `yt-dlp` subprocess | Python class is cleaner, better error handling |
| APScheduler 4.x | Still alpha as of 2026 |
| `gunicorn` | Multi-process conflicts with single scheduler |
| Alpine base image | musl libc breaks yt-dlp C extension dependencies |
| Persistent volume for /tmp | Breaks ephemeral contract — registry resets, volume doesn't |

---

## Dockerfile Structure

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**requirements.txt:**
```
fastapi==0.135.1
uvicorn[standard]==0.41.0
yt-dlp  # no version pin — always latest
apscheduler==3.11.2
anyio
python-multipart
```

---

## Coolify Deployment

- Environment variables: `API_KEY`, `TEMP_DIR` (default `/tmp/videos`), `TTL_HOURS` (default `1`)
- Health endpoint: `GET /health` — Coolify uses this for container readiness
- Traefik proxy timeout: must configure explicit timeout label (default 60s may be too short for large videos)
- No persistent volume needed — temp files are ephemeral by design

---

## Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Package versions | HIGH | Verified against PyPI index directly |
| yt-dlp latest | HIGH | Verified against GitHub Releases API |
| Integration patterns | MEDIUM | Official library docs + community patterns |
| Docker/Coolify patterns | MEDIUM | Standard patterns, well-established |
| iOS Shortcuts timeout | LOW | Hardcoded limit unconfirmed — verify at integration time |

---

## Open Questions

- iOS Shortcuts HTTP timeout: if a 1080p video takes >60s to download, sync design breaks. Consider size/duration guard.
- Traefik timeout: exact default in current Coolify release — verify at deploy time.
- YouTube PO token enforcement: does latest yt-dlp handle transparently? Verify at project start.
