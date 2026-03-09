---
phase: 01-core-application
plan: 02
type: execute
wave: 2
depends_on: ["01"]
files_modified:
  - main.py
autonomous: true
requirements:
  - DL-01
  - DL-02
  - FILE-01
  - FILE-02
  - SEC-02

must_haves:
  truths:
    - "POST /download with valid URL, quality, and correct X-API-Key returns JSON with download_url, expires_at, filename, title, duration"
    - "GET /files/{id} returns the binary file with correct Content-Type and Content-Disposition headers"
    - "GET /files/{id} for a non-existent ID returns 404 structured JSON"
    - "GET /files/{id} for an expired file returns 410 structured JSON"
    - "POST /download with a YouTube playlist URL returns 422 structured JSON"
    - "yt-dlp download runs in a thread (never blocking the asyncio event loop)"
  artifacts:
    - path: "main.py"
      provides: "POST /download and GET /files/{file_id} route implementations"
      contains: "download_video"
    - path: "main.py"
      provides: "playlist detection via _type check before download"
      contains: "_check_playlist"
  key_links:
    - from: "POST /download handler"
      to: "download_video() helper"
      via: "await asyncio.to_thread(_blocking_download)"
      pattern: "asyncio\\.to_thread"
    - from: "download_video()"
      to: "FileRegistry"
      via: "register_file(FileRecord(...))"
      pattern: "register_file"
    - from: "POST /download handler"
      to: "_check_playlist()"
      via: "called before download begins"
      pattern: "_check_playlist"
    - from: "GET /files/{file_id} handler"
      to: "FileResponse"
      via: "FastAPI FileResponse with path, filename, media_type"
      pattern: "FileResponse"
---

<objective>
Implement the two core API routes — POST /download and GET /files/{file_id} — completing the full request lifecycle: playlist detection → async yt-dlp download → UUID-based file storage → FileRegistry registration → time-limited URL generation → binary file serving with correct headers.

Purpose: This is the primary value delivery of Phase 1. After this plan, the service can accept a video URL and return a working download link.

Output: main.py gains POST /download and GET /files/{file_id} implementations. The file already has all scaffolding from Plan 01 (auth, error handlers, FileRegistry, scheduler).
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

<interfaces>
<!-- Key contracts from Plan 01's main.py that this plan builds on. -->

FileRecord dataclass (defined in Plan 01):
```python
@dataclass
class FileRecord:
    file_id: str
    path: str
    filename: str
    title: str
    duration: int        # seconds
    expires_at: datetime
    content_type: str
```

FileRegistry functions (defined in Plan 01):
```python
def register_file(record: FileRecord) -> None: ...  # thread-safe, uses registry_lock
def get_file(file_id: str) -> FileRecord | None: ...  # thread-safe, uses registry_lock
```

Auth dependency (defined in Plan 01):
```python
async def verify_api_key(key: str = Security(api_key_header)) -> str: ...
# Raises 401 if key missing or wrong
```

Constants (defined in Plan 01):
```python
DOWNLOAD_DIR: str          # e.g. "/tmp/downloads"
TTL_HOURS: int = 1
QUALITY_MAP: dict[str, str]  # "best"|"1080p"|"720p"|"480p"|"audio-only" → yt-dlp format string
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Pydantic request/response models + playlist detection helper</name>
  <files>main.py</files>
  <behavior>
    - DownloadRequest has fields: url (str, required), quality (Literal["best","1080p","720p","480p","audio-only"], default "best")
    - DownloadResponse has fields: download_url (str), expires_at (datetime), filename (str), title (str), duration (int)
    - _check_playlist(url) returns True if yt-dlp reports _type == "playlist" using extract_info(download=False, process=False)
    - _check_playlist uses quiet=True, no_warnings=True YoutubeDL options
    - _check_playlist is a plain synchronous function (called via asyncio.to_thread in the route)
  </behavior>
  <action>
Add to main.py (after the existing FileRecord dataclass and before route definitions):

**Pydantic models:**
```python
from pydantic import BaseModel
from typing import Literal

class DownloadRequest(BaseModel):
    url: str
    quality: Literal["best", "1080p", "720p", "480p", "audio-only"] = "best"

class DownloadResponse(BaseModel):
    download_url: str
    expires_at: datetime
    filename: str
    title: str
    duration: int
```

**Playlist detection helper (synchronous — called via asyncio.to_thread):**
```python
def _check_playlist(url: str) -> bool:
    """Returns True if the URL resolves to a playlist. Synchronous — use via asyncio.to_thread."""
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
    return info.get("_type") == "playlist"
```

Note: yt-dlp import goes in the imports section at the top of the file (`import yt_dlp`).
  </action>
  <verify>
    <automated>cd /Users/mehmet.tanas/personal-dev/video-downloader && python -c "
import os
os.environ['API_KEY'] = 'test-key'
import main
assert hasattr(main, 'DownloadRequest'), 'DownloadRequest missing'
assert hasattr(main, 'DownloadResponse'), 'DownloadResponse missing'
assert hasattr(main, '_check_playlist'), '_check_playlist missing'
# Validate model fields
req = main.DownloadRequest(url='http://example.com')
assert req.quality == 'best', 'default quality should be best'
print('OK')
"</automated>
  </verify>
  <done>DownloadRequest and DownloadResponse Pydantic models exist in main.py. _check_playlist() function defined. Model fields match spec exactly.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: POST /download and GET /files/{file_id} route implementations</name>
  <files>main.py</files>
  <behavior>
    - POST /download requires auth (Depends(verify_api_key))
    - POST /download: if _check_playlist(url) is True → raise HTTPException 422 with detail "Playlist URLs are not supported"
    - POST /download: calls download_video(url, quality) via asyncio.to_thread (the yt-dlp I/O runs in a thread)
    - download_video() is a synchronous function; uses UUID-prefix outtmpl; returns dict with path, filename, title, duration, content_type
    - After download, glob for {file_id}.* to find actual file (handles postprocessor extension changes)
    - FileRecord is registered with expires_at = datetime.utcnow() + timedelta(hours=TTL_HOURS)
    - download_url in response is constructed as "{request.base_url}files/{file_id}"
    - GET /files/{file_id} requires auth (Depends(verify_api_key))
    - GET /files/{file_id}: if file_id not in registry → 404 JSON
    - GET /files/{file_id}: if record.expires_at < datetime.utcnow() → 410 JSON
    - GET /files/{file_id}: if file not found on disk (race with cleanup) → 404 JSON
    - GET /files/{file_id}: returns FastAPI FileResponse(path, filename=record.filename, media_type=record.content_type)
    - content_type: "audio/mp4" for audio-only, "video/mp4" for all video qualities
    - yt-dlp options include: noplaylist=True (belt-and-suspenders), merge_output_format="mp4" for non-audio-only, quiet=True, no_warnings=True
  </behavior>
  <action>
Add the following to main.py in the routes section (after the existing GET /health route). Replace the placeholder comment from Plan 01.

**download_video() synchronous helper (called via asyncio.to_thread):**
```python
def download_video(url: str, quality: str, file_id: str) -> dict:
    """Synchronous yt-dlp download. Call via asyncio.to_thread — never call directly from async."""
    is_audio_only = quality == "audio-only"
    ydl_opts = {
        "format": QUALITY_MAP[quality],
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if not is_audio_only:
        ydl_opts["merge_output_format"] = "mp4"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Find actual output file (extension may differ from outtmpl due to postprocessors)
    matches = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_id}.*"))
    if not matches:
        raise RuntimeError(f"Download completed but output file not found for {file_id}")
    actual_path = matches[0]
    actual_filename = os.path.basename(actual_path)
    content_type = "audio/mp4" if is_audio_only else "video/mp4"

    return {
        "path": actual_path,
        "filename": actual_filename,
        "title": info.get("title", "video"),
        "duration": int(info.get("duration") or 0),
        "content_type": content_type,
    }
```

Add `import glob` to the imports section.

**POST /download route:**
```python
@app.post("/download", response_model=DownloadResponse)
async def download(request: Request, body: DownloadRequest, _: str = Depends(verify_api_key)):
    # Playlist check (runs in thread to avoid blocking event loop)
    is_playlist = await asyncio.to_thread(_check_playlist, body.url)
    if is_playlist:
        raise HTTPException(status_code=422, detail="Playlist URLs are not supported")

    file_id = str(uuid.uuid4())
    result = await asyncio.to_thread(download_video, body.url, body.quality, file_id)

    expires_at = datetime.utcnow() + timedelta(hours=TTL_HOURS)
    record = FileRecord(
        file_id=file_id,
        path=result["path"],
        filename=result["filename"],
        title=result["title"],
        duration=result["duration"],
        expires_at=expires_at,
        content_type=result["content_type"],
    )
    register_file(record)

    download_url = str(request.base_url) + f"files/{file_id}"
    return DownloadResponse(
        download_url=download_url,
        expires_at=expires_at,
        filename=result["filename"],
        title=result["title"],
        duration=result["duration"],
    )
```

Add these imports if not already present: `import uuid`, `from datetime import timedelta`, `from fastapi import Request`.

**GET /files/{file_id} route:**
```python
@app.get("/files/{file_id}")
async def serve_file(file_id: str, _: str = Depends(verify_api_key)):
    record = get_file(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="File has expired")
    if not os.path.exists(record.path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(
        path=record.path,
        filename=record.filename,
        media_type=record.content_type,
    )
```

Add import: `from fastapi.responses import FileResponse`.
  </action>
  <verify>
    <automated>cd /Users/mehmet.tanas/personal-dev/video-downloader && python -c "
import os
os.environ['API_KEY'] = 'test-key'
import main
import inspect

# Check routes exist
routes = {r.path: r for r in main.app.routes}
assert '/download' in routes, 'POST /download route missing'
assert '/files/{file_id}' in routes, 'GET /files/{file_id} route missing'

# Check helpers exist
assert hasattr(main, 'download_video'), 'download_video missing'
assert hasattr(main, '_check_playlist'), '_check_playlist missing'

# Check download_video is synchronous (not async)
assert not inspect.iscoroutinefunction(main.download_video), 'download_video must be sync (called via to_thread)'

# Check _check_playlist is synchronous
assert not inspect.iscoroutinefunction(main._check_playlist), '_check_playlist must be sync'

print('OK')
"</automated>
  </verify>
  <done>POST /download and GET /files/{file_id} routes exist and are correctly wired. download_video() is synchronous. All imports resolve. App starts without error.</done>
</task>

</tasks>

<verification>
After both tasks complete, run a functional smoke test (non-YouTube URL to avoid PO Token issue during automated checks — YouTube test happens in Plan 03):

```bash
cd /Users/mehmet.tanas/personal-dev/video-downloader
API_KEY=test-key uvicorn main:app --port 8000 &
sleep 2

# Health still works
curl -s http://localhost:8000/health
# Expected: {"status":"ok"}

# Missing auth on /download → 401
curl -s -X POST http://localhost:8000/download \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","quality":"best"}'
# Expected: 401 JSON

# Missing file → 404
curl -s -H "X-API-Key: test-key" http://localhost:8000/files/nonexistent-id
# Expected: {"error":"File not found","status_code":404}

# Playlist URL → 422 (use a known YouTube playlist URL)
curl -s -X POST http://localhost:8000/download \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d '{"url":"https://www.youtube.com/playlist?list=PLbpi6ZahtOH6Ar_3GPy3workInvalidXYZ","quality":"best"}'
# Expected: 422 JSON with "Playlist URLs are not supported"

kill %1
```

Note: Actual YouTube download test with a real video URL is the P0 verification in Plan 03 (checkpoint).
</verification>

<success_criteria>
- main.py has POST /download and GET /files/{file_id} routes
- download_video() is a synchronous function called via asyncio.to_thread (never blocking event loop directly)
- _check_playlist() is synchronous, called via asyncio.to_thread
- Playlist URLs return 422 with structured JSON
- Non-existent file_id returns 404 JSON
- Expired file_id returns 410 JSON (verified by manually setting expires_at in the past)
- Successful download returns JSON with all 5 required fields: download_url, expires_at, filename, title, duration
- GET /files/{file_id} returns binary file with Content-Disposition header
</success_criteria>

<output>
After completion, create `.planning/phases/01-core-application/01-02-SUMMARY.md` with:
- What was built
- Quality fallback behavior chosen (if any)
- content_type mapping decisions
- Any yt-dlp behavior surprises
- Verification results
</output>
