---
phase: 01-core-application
plan: 03
type: execute
wave: 3
depends_on: ["01", "02"]
files_modified:
  - main.py
autonomous: false
requirements:
  - DL-01
  - DL-02
  - FILE-01
  - FILE-02
  - SEC-01
  - SEC-02
  - OPS-01
  - OPS-02
  - OPS-03

must_haves:
  truths:
    - "A real YouTube video URL (not playlist) downloads successfully and returns a working download_url"
    - "The download_url can be used to download the actual binary video file"
    - "All 5 Phase 1 success criteria from ROADMAP.md are verified as TRUE"
  artifacts:
    - path: "main.py"
      provides: "Complete, working Phase 1 application — all routes, auth, scheduler, error handling"
      contains: "verify_api_key"
  key_links:
    - from: "Real YouTube URL"
      to: "binary file on disk"
      via: "POST /download → yt-dlp → FileRegistry → GET /files/{id}"
      pattern: "download_url"
---

<objective>
End-to-end P0 verification: test the complete download flow with a real YouTube URL, verify all Phase 1 success criteria are met, and fix any issues discovered (YouTube PO Token 403, filename resolution bugs, header issues).

Purpose: The RESEARCH.md flags YouTube PO Token behavior in server environments as P0 — it MUST be tested before Phase 1 is declared complete. This checkpoint plan surfaces any real-world issues that automated unit tests cannot catch.

Output: A verified, working Phase 1 application. Any PO Token or other issues discovered are fixed here. The phase is not complete until a real YouTube video downloads and serves correctly.
</objective>

<execution_context>
@/Users/mehmet.tanas/.claude/get-shit-done/workflows/execute-plan.md
@/Users/mehmet.tanas/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phases/01-core-application/01-CONTEXT.md
@.planning/phases/01-core-application/01-RESEARCH.md
@.planning/phases/01-core-application/01-01-SUMMARY.md
@.planning/phases/01-core-application/01-02-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Run full Phase 1 automated verification suite</name>
  <files>main.py</files>
  <action>
Run the complete automated verification sequence against the running server. Fix any failures found.

**Setup:**
```bash
cd /Users/mehmet.tanas/personal-dev/video-downloader
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set API_KEY to a test value
echo "API_KEY=phase1-test-key" > .env
API_KEY=phase1-test-key uvicorn main:app --port 8000 &
sleep 2
```

**Run each check in order — fix any failure before proceeding:**

1. Health check (OPS-02):
```bash
curl -s http://localhost:8000/health
# Must return: {"status":"ok"} with 200
```

2. Auth enforcement (SEC-01) — missing key:
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/download \
  -H "Content-Type: application/json" -d '{"url":"x","quality":"best"}'
# Must return: 401
```

3. Auth enforcement (SEC-01) — wrong key:
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/download \
  -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"url":"x","quality":"best"}'
# Must return: 401
```

4. Structured errors (OPS-03) — 404 for unknown file:
```bash
curl -s -H "X-API-Key: phase1-test-key" http://localhost:8000/files/00000000-0000-0000-0000-000000000000
# Must return JSON with "error" field, status 404
```

5. Structured errors (OPS-03) — validation error for bad quality:
```bash
curl -s -X POST http://localhost:8000/download \
  -H "X-API-Key: phase1-test-key" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","quality":"invalid"}'
# Must return JSON with "error" or "detail" field, status 422
```

**Fix any failures** before proceeding to the YouTube test in Task 2 (human checkpoint).

After fixes, kill the server: `kill %1` (or `pkill -f "uvicorn main:app"`).
  </action>
  <verify>
    <automated>cd /Users/mehmet.tanas/personal-dev/video-downloader && python -c "
import os, subprocess, time, sys

os.environ['API_KEY'] = 'phase1-test-key'
import main
import inspect

# Structural checks
assert hasattr(main, 'app')
assert hasattr(main, 'download_video')
assert hasattr(main, 'cleanup_expired')
assert hasattr(main, 'QUALITY_MAP')
assert not inspect.iscoroutinefunction(main.download_video), 'download_video must be sync'
routes = {r.path for r in main.app.routes}
assert '/health' in routes
assert '/download' in routes
assert '/files/{file_id}' in routes
print('Structural checks: OK')
"</automated>
  </verify>
  <done>All 5 automated checks pass (health 200, auth 401 ×2, 404 JSON, 422 JSON). Any code fixes applied and committed to main.py.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>
A complete FastAPI service (Plans 01 + 02) that wraps yt-dlp for synchronous video download. The service exposes POST /download and GET /files/{file_id}, enforces X-API-Key auth, returns structured JSON errors, and runs a background cleanup scheduler.

P0 risk (from RESEARCH.md): YouTube may return HTTP 403 in server environments due to PO Token requirements. This checkpoint tests that risk with a real YouTube URL.
  </what-built>
  <how-to-verify>
**Start the server:**
```bash
cd /Users/mehmet.tanas/personal-dev/video-downloader
echo "API_KEY=phase1-test-key" > .env
API_KEY=phase1-test-key uvicorn main:app --port 8000
```

**Test 1 — Real YouTube video download (P0 test):**
Use a short YouTube video (ideally under 1 minute for speed). For example:
```bash
curl -s -X POST http://localhost:8000/download \
  -H "Content-Type: application/json" \
  -H "X-API-Key: phase1-test-key" \
  -d '{"url":"https://www.youtube.com/watch?v=jNQXAC9IVRw","quality":"720p"}'
```
("Me at the zoo" — YouTube's first video, 19 seconds)

Expected response shape:
```json
{
  "download_url": "http://127.0.0.1:8000/files/...",
  "expires_at": "2026-...",
  "filename": "...",
  "title": "Me at the zoo",
  "duration": 19
}
```

**Test 2 — Serve the downloaded file:**
Copy the `download_url` from Test 1's response and request it:
```bash
curl -s -o /tmp/test-video.mp4 -H "X-API-Key: phase1-test-key" "<download_url>"
ls -lh /tmp/test-video.mp4
# Must be non-zero size
```

**Test 3 — Playlist rejection (SEC-02):**
```bash
curl -s -X POST http://localhost:8000/download \
  -H "Content-Type: application/json" \
  -H "X-API-Key: phase1-test-key" \
  -d '{"url":"https://www.youtube.com/playlist?list=PLbpi6ZahtOH6Ar_3GPy3gPwFZgFnF4VjG","quality":"best"}'
# Must return 422 with "Playlist URLs are not supported"
```

**If YouTube returns 403 (PO Token issue):**
This is the expected P0 risk. Return to Claude with the exact error message. Claude will implement one of these fixes (in order of preference):
1. Add `extractor_args: {"youtube": {"player_client": ["ios"]}}` to yt-dlp opts
2. Use cookies-from-browser option (requires user to be logged into YouTube in browser)
3. Research bgutil-ytdlp-pot-provider plugin

**Report back:** "approved" if all 3 tests pass, or describe the exact error you see.
  </how-to-verify>
  <resume-signal>Type "approved" if all tests pass. Or describe what failed (include the exact error/response body).</resume-signal>
</task>

</tasks>

<verification>
Phase 1 is complete when ALL of the following are TRUE (from ROADMAP.md Phase 1 Success Criteria):

1. POST /download with valid URL + quality + correct X-API-Key returns JSON containing download_url, expires_at, filename, title, and duration ✓
2. GET /files/{id} returns binary file with correct Content-Type and Content-Disposition; expired/non-existent ID returns 410/404 respectively ✓
3. Missing/wrong X-API-Key returns 401; playlist URL returns 422 ✓
4. Files older than 1 hour are auto-deleted by scheduler (runs every 5 minutes); disk doesn't accumulate stale files ✓
5. GET /health returns 200; all API errors return structured JSON (never raw tracebacks) ✓
</verification>

<success_criteria>
- Real YouTube video downloads successfully (no 403, no FileNotFoundError)
- download_url resolves to the actual binary file
- All Phase 1 ROADMAP success criteria verified as TRUE
- No PO Token 403 errors (or workaround implemented and tested)
- Phase 1 declared complete
</success_criteria>

<output>
After completion, create `.planning/phases/01-core-application/01-03-SUMMARY.md` with:
- YouTube PO Token test result (pass/fail/workaround applied)
- Any bugs found and fixed during verification
- Final state of main.py
- Confirmation that all 5 ROADMAP success criteria are met
</output>
