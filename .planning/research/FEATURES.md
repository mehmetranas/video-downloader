# Feature Research

**Domain:** Private video downloader REST API (yt-dlp based, personal use)
**Researched:** 2026-03-09
**Confidence:** HIGH (yt-dlp inspected live at v2026.02.21; project scope from PROJECT.md)

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| POST /download endpoint accepting a URL | Core purpose of the service; no URL = no service | LOW | Must accept JSON body with `url` field |
| Quality/format selection | yt-dlp natively supports `best`, `bestvideo+bestaudio`, height-based filters (720, 1080, etc.) | LOW | Map user-friendly labels (`720p`, `best`, `audio`) to yt-dlp format strings |
| Audio-only extraction | Common use case (podcasts, music); yt-dlp `-x --audio-format mp3/m4a` makes this trivial | LOW | Requires ffmpeg in container |
| Temporary download URL in response | Without a download URL, caller can't retrieve the file | LOW | `{download_url, expires_at, filename}` — matches PROJECT.md spec |
| GET /files/{id} endpoint | Needed to serve the temporary file to the caller | LOW | Stream file from disk with correct Content-Type and Content-Disposition |
| TTL-based file cleanup | Disk will fill otherwise; central to the "ephemeral" value prop | MEDIUM | Background task (APScheduler or asyncio loop) scanning /tmp/videos, deleting expired files |
| API key authentication | Without auth, service is open to the internet | LOW | Single static key in `X-API-Key` header; 401 on mismatch |
| Structured error responses | Callers (iOS Shortcuts) need machine-readable errors to show meaningful messages | LOW | `{error: "...", code: "PLATFORM_UNSUPPORTED"}` JSON, not raw 500 stack traces |
| Platform-agnostic URL handling | yt-dlp supports 1,872 extractors (verified live); caller should not need to specify the platform | LOW | Pass URL directly to yt-dlp; extractor chosen automatically |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Metadata extraction in response | Return `title`, `duration`, `thumbnail_url`, `uploader`, `ext` alongside download_url | LOW | yt-dlp info dict exposes all these; costs near-zero since extraction already happened |
| Filename sanitization | Downloaded file name is human-readable and safe for iOS Files app | LOW | yt-dlp `--restrict-filenames` + custom outtmpl template; avoid UUID-only names |
| Health check endpoint | GET /health returns 200 + `{"status": "ok", "version": "..."}` — useful for Coolify deployment monitoring | LOW | Trivial to add; enables uptime checks |
| Explicit expiry time in response | `expires_at` ISO timestamp lets iOS Shortcut show "expires in 58 minutes" | LOW | Compute at download time: `now + 3600` |
| Content-Type and Content-Disposition headers on file serving | iOS Shortcuts needs correct MIME type to route file to Photos vs Files app | LOW | Detect from file extension; `video/mp4`, `audio/mpeg`, etc. |
| Format negotiation by container | Allow caller to request `mp4` container explicitly (needed for iOS compatibility) | MEDIUM | Map to yt-dlp `--merge-output-format mp4 --remux-video mp4`; requires ffmpeg |
| Concurrent fragment downloading | Faster downloads for DASH/HLS streams; yt-dlp `--concurrent-fragments N` | LOW | Set N=4 as default; no API surface needed — internal tuning |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Async download with polling (job queue) | Long downloads benefit from async; caller checks status | iOS Shortcuts has no polling loop without complex multi-step shortcuts; adds a job store, polling endpoint, state machine | Sync POST with appropriate timeout (60-120s); most videos under 500MB download in <30s on good connections |
| Progress reporting via SSE/WebSocket | Nice UX to see "47% done" | Adds protocol complexity; iOS Shortcuts cannot consume SSE or WebSockets natively | Return download_url synchronously; client doesn't need progress |
| Multi-user API key management | Sounds useful if shared | Adds key storage, rotation, revocation logic; entire PROJECT.md scope is single personal user | Single env-var key; if sharing is ever needed, create separate deployment instances |
| Playlist/batch download | Download entire YouTube playlist at once | Disk usage is unbounded; TTL cleanup becomes complex for multi-file downloads; async becomes necessary | Reject playlist URLs at the API layer with a clear error; caller downloads individual videos |
| Dashboard / admin UI | Manage files, view logs visually | Out of scope per PROJECT.md; adds frontend build, auth session management, port exposure | Use container logs + file system inspection via Coolify |
| Persistent storage / user library | Keep videos indefinitely for re-download | Negates the privacy/ephemeral value prop; storage costs grow unboundedly | 1-hour TTL is intentional; if permanence is needed, caller saves the file locally |
| Subtitle download and embedding | Useful for accessibility | Adds ffmpeg post-processing time; file size increases; complexity of subtitle format selection | Out of scope for personal use; yt-dlp supports it if ever needed (`--write-subs --embed-subs`) |
| Rate limiting | Protect from abuse | Service is behind a static API key with a single user; rate limiting adds Redis or in-memory complexity with no real benefit | API key is the gate; no need for per-IP or per-key rate limits on a personal service |
| Webhook / callback on completion | Notify caller when async download is done | Requires async job model first (already anti-featured); webhooks need reliable delivery infrastructure | Sync download returns result immediately |
| Thumbnail embedding in video file | Makes the file nicer in media players | Requires ffmpeg post-processing step; adds 1-5 seconds; no real benefit for iOS Photos | Return `thumbnail_url` in JSON if caller wants the image separately |

---

## Feature Dependencies

```
[API key auth]
    └──required by──> [POST /download endpoint]
                           └──requires──> [yt-dlp invocation]
                                              └──requires──> [ffmpeg] (for audio-only, mp4 remux, format merge)
                           └──produces──> [temp file on disk]
                                              └──served by──> [GET /files/{id} endpoint]
                                              └──cleaned by──> [TTL background cleanup]

[Quality/format selection] ──parameterizes──> [yt-dlp invocation]
[Metadata extraction] ──reads from──> [yt-dlp info dict] (produced during same invocation)
[Filename sanitization] ──applied at──> [yt-dlp invocation] (outtmpl option)
[Health check endpoint] ──independent──> (no dependencies)
```

### Dependency Notes

- **ffmpeg required for audio-only and mp4 remux:** yt-dlp uses ffmpeg as a postprocessor for `-x` (audio extract) and `--remux-video mp4`. Must be present in Docker image. Without it, format conversion silently fails or errors.
- **Metadata extraction is free:** yt-dlp's info dict is populated during format selection before the download starts. Returning `title`, `duration`, `ext`, `uploader` costs no extra requests.
- **TTL cleanup depends on temp file registration:** To clean up files at the right time, the API must record `(file_path, expires_at)` in-memory (or a lightweight store) at download time. Cleanup job reads this registry.
- **GET /files/{id} depends on stable file ID scheme:** The ID in the download URL must map deterministically to a file path. UUIDs assigned at download time and stored in-memory registry is the simplest approach.

---

## MVP Definition

### Launch With (v1)

Minimum viable product — what's needed to validate the concept.

- [ ] `POST /download` — accepts `{url, quality}`, returns `{download_url, expires_at, filename, title, duration}` — core value
- [ ] Quality mapping — `best`, `1080p`, `720p`, `480p`, `audio` mapped to yt-dlp format strings — callers need control
- [ ] `GET /files/{id}` — serves file with correct Content-Type/Content-Disposition headers — required to actually retrieve the file
- [ ] API key auth via `X-API-Key` header — prevents open access
- [ ] 1-hour TTL + background cleanup — prevents disk exhaustion
- [ ] Structured JSON error responses — iOS Shortcuts needs machine-readable errors, not HTML 500 pages
- [ ] `GET /health` — needed for Coolify deployment health checks
- [ ] Docker image with ffmpeg — required for audio extraction and mp4 remux

### Add After Validation (v1.x)

Features to add once core is working.

- [ ] `mp4` container enforcement option — add when iOS compatibility issues surface (iOS Photos requires H.264/AAC in mp4)
- [ ] Richer metadata in response (`thumbnail_url`, `uploader`, `webpage_url`) — add if iOS Shortcut UI wants to preview before saving
- [ ] Configurable TTL via env var — add if 1 hour proves too short for large files on slow connections

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] Multiple quality presets as named aliases — defer; `best/720p/480p/audio` covers 95% of use cases
- [ ] Platform-specific extractor args (e.g., YouTube cookies for age-restricted content) — defer; adds cookie management complexity
- [ ] Concurrent fragment tuning exposed as API parameter — defer; internal default of 4 is sufficient

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| POST /download with yt-dlp | HIGH | LOW | P1 |
| Quality/format selection | HIGH | LOW | P1 |
| GET /files/{id} file serving | HIGH | LOW | P1 |
| API key auth | HIGH | LOW | P1 |
| TTL cleanup background task | HIGH | MEDIUM | P1 |
| Structured error responses | HIGH | LOW | P1 |
| Health check endpoint | MEDIUM | LOW | P1 |
| Metadata in response (title, duration) | MEDIUM | LOW | P1 |
| Filename sanitization | MEDIUM | LOW | P1 |
| mp4 container enforcement | MEDIUM | LOW | P2 |
| Configurable TTL | LOW | LOW | P2 |
| Richer metadata (thumbnail_url, uploader) | LOW | LOW | P2 |
| Audio format selection (mp3 vs m4a) | LOW | LOW | P3 |
| Concurrent fragment tuning | LOW | LOW | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

---

## Competitor Feature Analysis

| Feature | Cobalt (cobalt.tools) | yt-dlp-web (community) | Our Approach |
|---------|----------------------|------------------------|--------------|
| Quality selection | Yes, UI dropdown | Varies by impl | API param: `quality` string |
| Audio-only | Yes | Most support it | `quality: "audio"` maps to `-x` |
| Temp URL | No — direct download | Varies | 1-hour TTL URL + separate GET |
| Auth | None (public service) | Varies | Static API key |
| Metadata in response | No | Sometimes | Return title, duration, expires_at always |
| Playlist support | Partial | Varies | Explicitly rejected — single video only |
| Async model | No | Some use queues | Sync — optimized for iOS Shortcuts simplicity |

*Note: Cobalt and community implementations surveyed from training data (HIGH confidence on Cobalt; MEDIUM on community implementations — not verified live due to unavailable web tools).*

---

## Sources

- yt-dlp v2026.02.21 `--help` output (inspected live, HIGH confidence)
- yt-dlp extractor count: 1,872 extractors (verified live, HIGH confidence)
- PROJECT.md requirements and constraints (HIGH confidence — authoritative for this project)
- yt-dlp format selection: `bestvideo+bestaudio/best`, height filters, `-x` audio extraction, `--merge-output-format mp4` (verified from live `--help`)
- yt-dlp preset aliases: `mp3`, `aac`, `mp4`, `mkv` (verified from live `--help`)
- iOS Shortcuts HTTP behavior: sync-only, no SSE/WebSocket support (MEDIUM confidence — training data, not verified live due to unavailable web tools)
- Coolify health check patterns: standard GET /health convention (MEDIUM confidence)

---
*Feature research for: Private video downloader REST API (yt-dlp based)*
*Researched: 2026-03-09*
