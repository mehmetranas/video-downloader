---
phase: 01-core-application
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - main.py
  - requirements.txt
  - .env.example
  - .gitignore
autonomous: true
requirements:
  - SEC-01
  - OPS-01
  - OPS-02
  - OPS-03

must_haves:
  truths:
    - "GET /health returns 200 with JSON body without any API key"
    - "All non-health endpoints return 401 when X-API-Key header is missing or wrong"
    - "All error responses are structured JSON (never raw tracebacks)"
    - "Background scheduler starts on app startup and stops on shutdown"
    - "Files older than 1 hour are removed by cleanup_expired() when called"
  artifacts:
    - path: "main.py"
      provides: "FastAPI app with lifespan, health endpoint, auth dependency, error handlers, FileRegistry, cleanup scheduler"
      contains: "verify_api_key"
    - path: "requirements.txt"
      provides: "Pinned dependencies"
      contains: "fastapi"
    - path: ".env.example"
      provides: "Template for required env vars"
      contains: "API_KEY"
  key_links:
    - from: "verify_api_key dependency"
      to: "protected route handlers"
      via: "Depends(verify_api_key)"
      pattern: "Depends\\(verify_api_key\\)"
    - from: "APScheduler BackgroundScheduler"
      to: "cleanup_expired function"
      via: "scheduler.add_job"
      pattern: "add_job.*cleanup_expired"
    - from: "lifespan context manager"
      to: "scheduler"
      via: "scheduler.start() / scheduler.shutdown()"
      pattern: "scheduler\\.start\\(\\)"
---

<objective>
Scaffold the complete FastAPI application foundation: project files, dependency declarations, app factory with lifespan, health endpoint, X-API-Key authentication dependency, structured error handlers for all exception types, the FileRegistry (in-memory dict + threading.Lock), and the APScheduler background cleanup job.

Purpose: Every other piece of Phase 1 is built on top of these foundations. Getting this right — especially the async event loop safety, thread-safe registry, and error handlers — prevents cascading issues in Plan 02.

Output: A runnable FastAPI app (uvicorn main:app) that responds to GET /health and rejects all other routes with 401. No download logic yet.
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
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Project files — requirements.txt, .env.example, .gitignore</name>
  <files>requirements.txt, .env.example, .gitignore</files>
  <behavior>
    - requirements.txt contains: fastapi[standard], uvicorn[standard], yt-dlp, APScheduler (3.x), python-dotenv, python-multipart
    - .env.example contains API_KEY= and DOWNLOAD_DIR= stubs with comments
    - .gitignore excludes: .env, downloads/, __pycache__/, *.pyc, .venv/
  </behavior>
  <action>
Create three files:

**requirements.txt** — pin to versions from RESEARCH.md:
```
fastapi[standard]==0.135.1
uvicorn[standard]
yt-dlp==2026.3.3
APScheduler==3.11.2
python-dotenv
python-multipart
```

**\.env.example**:
```
# Copy to .env and fill in values
API_KEY=your-secret-key-here
DOWNLOAD_DIR=/tmp/downloads
```

**.gitignore**:
```
.env
downloads/
__pycache__/
*.pyc
*.pyo
.venv/
venv/
*.egg-info/
dist/
```
  </action>
  <verify>
    <automated>test -f requirements.txt && grep -q "fastapi" requirements.txt && test -f .env.example && grep -q "API_KEY" .env.example && test -f .gitignore && grep -q ".env" .gitignore && echo "OK"</automated>
  </verify>
  <done>All three files exist with correct content. requirements.txt has all 6 dependencies. .env.example has both env var stubs. .gitignore excludes .env and downloads/.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: main.py — app skeleton, lifespan, health, auth, error handlers, FileRegistry, scheduler</name>
  <files>main.py</files>
  <behavior>
    - GET /health returns {"status": "ok"} with 200, NO auth required
    - POST to any other route with no X-API-Key returns 401 JSON: {"error": "Invalid or missing API key", "status_code": 401}
    - POST to any other route with wrong X-API-Key returns 401 JSON
    - HTTPException returns {"error": str, "status_code": int}
    - RequestValidationError returns {"error": "Validation error", "detail": [...]}
    - Uncaught Exception returns {"error": "Internal server error"} with 500
    - Startup guard: if API_KEY env var is not set or empty, raise RuntimeError at startup
    - cleanup_expired() removes files where expires_at < datetime.utcnow() and deletes from disk; thread-safe via registry_lock
    - scheduler runs cleanup_expired every 5 minutes via IntervalTrigger; starts in lifespan, shuts down after yield
    - FileRecord is a dataclass with fields: file_id, path, filename, title, duration, expires_at, content_type
    - files dict and registry_lock are module-level; register_file() and get_file() use registry_lock
  </behavior>
  <action>
Write main.py as a single file containing everything below. Do NOT split into modules (per locked user decision).

**Structure order in the file:**
1. Imports (stdlib, then third-party)
2. Env var loading (python-dotenv load_dotenv(), then os.environ.get)
3. Startup guard: `if not API_KEY: raise RuntimeError("API_KEY env var must be set")`
4. Constants: DOWNLOAD_DIR (default "/tmp/downloads"), TTL_HOURS = 1, QUALITY_MAP dict
5. FileRecord dataclass
6. FileRegistry: module-level `files: dict[str, FileRecord] = {}`, `registry_lock = threading.Lock()`, `register_file()`, `get_file()`, `cleanup_expired()` functions
7. APScheduler: `scheduler = BackgroundScheduler()`
8. Lifespan context manager (start scheduler, yield, shutdown)
9. FastAPI app instantiation with lifespan=lifespan
10. Exception handlers (StarletteHTTPException, RequestValidationError, generic Exception)
11. Auth dependency: `api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)`, `verify_api_key()` async function
12. Routes: GET /health (no auth), placeholder comment for POST /download and GET /files/{file_id} (to be added in Plan 02)

**Key implementation details:**
- Use `from contextlib import asynccontextmanager` for lifespan
- `load_dotenv()` called before any `os.environ.get` calls
- DOWNLOAD_DIR created with `os.makedirs(DOWNLOAD_DIR, exist_ok=True)` at module level (after env loading)
- cleanup_expired: acquire registry_lock to collect expired keys, then release before os.remove to avoid holding lock during I/O; catch FileNotFoundError silently
- verify_api_key raises `HTTPException(status_code=401, detail="Invalid or missing API key")`
- Health route: `@app.get("/health")` — no dependencies
- QUALITY_MAP per RESEARCH.md Pattern 8 (5 quality strings → yt-dlp format strings)

**Do NOT implement yet:** POST /download, GET /files/{file_id} — those are Plan 02.
  </action>
  <verify>
    <automated>cd /Users/mehmet.tanas/personal-dev/video-downloader && python -c "
import os
os.environ['API_KEY'] = 'test-key'
import main
assert hasattr(main, 'app'), 'app missing'
assert hasattr(main, 'FileRecord'), 'FileRecord missing'
assert hasattr(main, 'cleanup_expired'), 'cleanup_expired missing'
assert hasattr(main, 'QUALITY_MAP'), 'QUALITY_MAP missing'
assert set(main.QUALITY_MAP.keys()) == {'best','1080p','720p','480p','audio-only'}, 'QUALITY_MAP keys wrong'
print('OK')
"</automated>
  </verify>
  <done>main.py imports cleanly (with API_KEY set). All structural elements exist. `uvicorn main:app --reload` starts without error. GET /health returns 200. A request without X-API-Key returns 401 JSON. Cleanup scheduler starts on app startup.</done>
</task>

</tasks>

<verification>
After both tasks complete, run:

```bash
cd /Users/mehmet.tanas/personal-dev/video-downloader
pip install -r requirements.txt
API_KEY=test-key uvicorn main:app --port 8000 &
sleep 2

# Health check (no auth required)
curl -s http://localhost:8000/health
# Expected: {"status":"ok"}

# Auth rejection — missing header
curl -s -X POST http://localhost:8000/download -H "Content-Type: application/json" -d '{"url":"x","quality":"best"}'
# Expected: {"error":"Invalid or missing API key","status_code":401}

# Auth rejection — wrong key
curl -s -X POST http://localhost:8000/download -H "X-API-Key: wrong" -H "Content-Type: application/json" -d '{"url":"x","quality":"best"}'
# Expected: 401 JSON

kill %1
```
</verification>

<success_criteria>
- `pip install -r requirements.txt` succeeds with no conflicts
- `uvicorn main:app` starts without errors when API_KEY is set
- `uvicorn main:app` raises RuntimeError at startup when API_KEY is not set
- GET /health → 200 {"status": "ok"} with no auth header
- POST /download with no auth → 401 structured JSON
- POST /download with wrong auth → 401 structured JSON
- No raw Python tracebacks ever appear in responses
- cleanup_expired() can be called without error (with empty registry)
</success_criteria>

<output>
After completion, create `.planning/phases/01-core-application/01-01-SUMMARY.md` with:
- What was built
- Key implementation choices made (scheduler library, error response shape, etc.)
- Any deviations from plan and why
- Verification results
</output>
