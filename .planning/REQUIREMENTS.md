# Requirements: Video Downloader API

**Defined:** 2026-03-09
**Core Value:** Bir video URL'si gönder, 1 saatlik geçici indirme linki al — hiçbir şey kalıcı depolanmaz.

## v1 Requirements

### Download

- [ ] **DL-01**: Kullanıcı video URL'si ve kalite parametresi (best/1080p/720p/480p/audio-only) ile POST /download isteği gönderebilir
- [ ] **DL-02**: Başarılı indirmede API `download_url`, `expires_at`, `filename`, `title`, `duration` içeren JSON döner

### File Serving

- [ ] **FILE-01**: Kullanıcı GET /files/{id} ile doğru Content-Type ve Content-Disposition header'larıyla binary dosyayı indirebilir
- [ ] **FILE-02**: GET /files/{id} kayıt yoksa 404, süresi dolmuşsa 410 döner

### Security

- [x] **SEC-01**: Tüm endpoint'ler (GET /health hariç) X-API-Key header doğrulaması gerektirir
- [ ] **SEC-02**: Playlist URL'leri 422 hatasıyla reddedilir

### Operations

- [x] **OPS-01**: Dosyalar 1 saatlik TTL sonrası arka planda otomatik silinir (5 dakikada bir çalışır)
- [x] **OPS-02**: GET /health endpoint Coolify container hazırlık kontrolü için hizmet durumunu döner
- [x] **OPS-03**: Tüm API hataları yapılandırılmış JSON formatında döner

### Deployment

- [ ] **DEPLOY-01**: Servis Coolify'a deploy edilebilir Docker container olarak çalışır
- [ ] **DEPLOY-02**: API_KEY ortam değişkeni ile yapılandırılabilir

## v2 Requirements

### Security Hardening

- **SEC-03**: SSRF koruması — private IP, loopback ve metadata URL'leri reddedilir
- **SEC-04**: İndirme isteğinde boyut/süre sınırı (iOS Shortcuts timeout koruması)

### iOS Compatibility

- **IOS-01**: mp4 container zorlama — iOS Photos için H.264/AAC mp4 garantisi
- **IOS-02**: Response'da thumbnail_url ve uploader metadata

### Operations

- **OPS-04**: Coolify Traefik proxy timeout yapılandırması (300s) — uzun indirmelerin kesilmesini önler
- **OPS-05**: TTL süresi env değişkeni ile yapılandırılabilir (varsayılan 1 saat)
- **OPS-06**: Audio format seçimi (mp3 vs m4a) API parametresi olarak

## Out of Scope

| Feature | Reason |
|---------|--------|
| Async download + job polling | iOS Shortcuts polling döngüsü yapamaz |
| SSE / WebSocket progress | iOS Shortcuts bu protokolleri desteklemez |
| Playlist / batch download | Sınırsız disk kullanımı, kapsam dışı |
| Kalıcı video depolama | Servisin amacı geçicilik |
| Çoklu API key yönetimi | Tek kullanıcı, tek key |
| Dashboard / admin arayüzü | Saf API servisi |
| Instagram/Twitter cookie auth | v1 best-effort; v2'de ele alınabilir |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DL-01 | Phase 1 | Pending |
| DL-02 | Phase 1 | Pending |
| FILE-01 | Phase 1 | Pending |
| FILE-02 | Phase 1 | Pending |
| SEC-01 | Phase 1 | Complete (01-01) |
| SEC-02 | Phase 1 | Pending |
| OPS-01 | Phase 1 | Complete (01-01) |
| OPS-02 | Phase 1 | Complete (01-01) |
| OPS-03 | Phase 1 | Complete (01-01) |
| DEPLOY-01 | Phase 2 | Pending |
| DEPLOY-02 | Phase 2 | Pending |

**Coverage:**
- v1 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-09*
*Last updated: 2026-03-09 after 01-01 plan completion (SEC-01, OPS-01, OPS-02, OPS-03 marked complete)*
