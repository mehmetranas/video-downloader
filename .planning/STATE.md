# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-09)

**Core value:** Send a video URL, get a 1-hour temporary download link — nothing is stored permanently.
**Current focus:** Phase 1 - Core Application

## Current Position

Phase: 1 of 2 (Core Application)
Plan: 3 of 3 in current phase
Status: Phase complete
Last activity: 2026-03-09 — Completed Plan 03: End-to-end P0 verification — all 5 Phase 1 success criteria verified TRUE

Progress: [█████░░░░░] 50%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: 5 min
- Total execution time: 0.17 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-core-application | 2 | 10 min | 5 min |

**Recent Trend:**
- Last 5 plans: 3 min, 7 min
- Trend: stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Sync download (POST blocks until complete) — iOS Shortcuts cannot implement async polling loops
- yt-dlp called via run_in_executor — must never block the async event loop; bake this in from the first line of download logic
- In-memory dict with threading.Lock for FileRegistry — no database or cache layer needed at this scope
- [01-01] BackgroundScheduler (not AsyncIOScheduler) — separate thread for file I/O cleanup avoids event loop blocking
- [01-01] Lock released before os.remove() in cleanup_expired() — avoids holding lock during slow disk I/O
- [01-01] Error response shape: {error, status_code} for HTTP; {error, detail} for validation; {error} for 500
- [01-01] Startup guard raises RuntimeError if API_KEY empty — prevents silent auth bypass with blank key
- [01-02] asyncio.to_thread for both _check_playlist and download_video — yt-dlp I/O never blocks the event loop
- [01-02] glob-based file resolution after yt-dlp download — postprocessors can change output extension (e.g., webm -> mp4)
- [01-02] content_type: audio/mp4 for audio-only, video/mp4 for all video qualities — deterministic mapping
- [01-02] noplaylist=True on yt-dlp options as belt-and-suspenders even after playlist guard check
- [01-03] nocheckcertificate: True in yt-dlp opts for both _check_playlist and download_video — self-signed SSL cert in network chain; required for target environment

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1 — RESOLVED]: YouTube PO token P0 risk did not materialize. SSL self-signed cert was the actual blocker; fixed with nocheckcertificate: True in yt-dlp opts.
- [Phase 2]: Traefik timeout label syntax for Coolify-bundled version is MEDIUM confidence — verify against live Coolify docs before writing production docker-compose

## Session Continuity

Last session: 2026-03-09
Stopped at: Completed 01-core-application/03-PLAN.md — Phase 1 complete. All 5 success criteria verified TRUE. Ready for Phase 2 (deployment).
Resume file: None
