# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-09)

**Core value:** Send a video URL, get a 1-hour temporary download link — nothing is stored permanently.
**Current focus:** Phase 1 - Core Application

## Current Position

Phase: 1 of 2 (Core Application)
Plan: 1 of 3 in current phase
Status: In progress
Last activity: 2026-03-09 — Completed Plan 01: FastAPI app foundation

Progress: [██░░░░░░░░] 17%

## Performance Metrics

**Velocity:**
- Total plans completed: 1
- Average duration: 3 min
- Total execution time: 0.05 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-core-application | 1 | 3 min | 3 min |

**Recent Trend:**
- Last 5 plans: 3 min
- Trend: baseline

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

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: YouTube PO token behavior in containerized environments is unconfirmed — treat real YouTube URL test as P0 verification step immediately in Phase 1
- [Phase 2]: Traefik timeout label syntax for Coolify-bundled version is MEDIUM confidence — verify against live Coolify docs before writing production docker-compose

## Session Continuity

Last session: 2026-03-09
Stopped at: Completed 01-core-application/01-PLAN.md — FastAPI app foundation scaffolded. Ready for Plan 02 (download routes).
Resume file: None
