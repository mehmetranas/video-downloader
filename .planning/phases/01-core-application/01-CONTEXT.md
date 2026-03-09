# Phase 1: Core Application - Context

**Gathered:** 2026-03-09
**Status:** Ready for planning

<domain>
## Phase Boundary

A locally runnable FastAPI service that accepts a video URL, downloads it via yt-dlp, returns a time-limited download URL, serves the binary file, and cleans up expired files automatically. No UI, no database, no deployment concerns — pure API logic.

</domain>

<decisions>
## Implementation Decisions

### Project Structure
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

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches for undecided areas.

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — greenfield project

### Established Patterns
- None — first code in this repo

### Integration Points
- Phase 2 will containerize this service — keep configuration (API key, file storage path) out of hardcoded values so env vars can override them cleanly

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-core-application*
*Context gathered: 2026-03-09*
