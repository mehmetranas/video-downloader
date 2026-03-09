# Roadmap: Video Downloader API

## Overview

Two phases: build the complete FastAPI application (download, serve, auth, cleanup), then containerize and deploy it to Coolify. The entire application logic ships in Phase 1 because all components share the FileRegistry and cannot be sensibly split. Phase 2 validates the container in a real Coolify environment and configures the Traefik proxy timeout that only manifests under production load.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Core Application** - Complete FastAPI service: download, file serving, auth, cleanup, and structured errors
- [ ] **Phase 2: Docker and Deployment** - Coolify-deployable Docker image with correct proxy timeout and env-based configuration

## Phase Details

### Phase 1: Core Application
**Goal**: A locally runnable API that accepts a video URL, downloads it via yt-dlp, returns a time-limited download URL, serves the binary file, and cleans up expired files automatically
**Depends on**: Nothing (first phase)
**Requirements**: DL-01, DL-02, FILE-01, FILE-02, SEC-01, SEC-02, OPS-01, OPS-02, OPS-03
**Success Criteria** (what must be TRUE):
  1. A POST /download request with a valid URL, quality parameter, and correct X-API-Key returns JSON containing download_url, expires_at, filename, title, and duration
  2. A GET /files/{id} request returns the binary file with correct Content-Type and Content-Disposition headers; requesting an expired or non-existent ID returns 410 or 404 respectively
  3. Any request missing or providing a wrong X-API-Key returns 401; a playlist URL returns 422
  4. Files older than 1 hour are automatically deleted by the background scheduler (runs every 5 minutes); disk does not accumulate stale files
  5. GET /health returns a 200 response and all API errors return structured JSON (never unformatted tracebacks)
**Plans**: TBD

### Phase 2: Docker and Deployment
**Goal**: The service runs in a Docker container on Coolify, survives proxy timeout constraints, and is fully configured via environment variables
**Depends on**: Phase 1
**Requirements**: DEPLOY-01, DEPLOY-02
**Success Criteria** (what must be TRUE):
  1. The Docker image builds successfully, includes ffmpeg, and starts the FastAPI service via uvicorn
  2. Coolify health check passes against GET /health and the service is reachable from an iOS Shortcut POST request
  3. API_KEY environment variable controls authentication — changing the env value changes which key is accepted without rebuilding the image
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Core Application | 0/? | Not started | - |
| 2. Docker and Deployment | 0/? | Not started | - |
