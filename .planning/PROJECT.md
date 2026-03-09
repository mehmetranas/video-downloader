# Video Downloader API

## What This Is

Özel bir REST API servisi — sosyal medya platformlarındaki (YouTube, Twitter/X, Instagram ve diğer yt-dlp destekli siteler) videoları POST isteğiyle indirip geçici bir indirme linki döner. Servis kişisel kullanım için tasarlanmış olup iOS Shortcuts ile entegre çalışır; videolar 1 saat sonra otomatik silinir.

## Core Value

Bir video URL'si gönder, 1 saatlik geçici indirme linki al — hiçbir şey kalıcı depolanmaz.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] API key ile korunan POST /download endpoint'i — URL + kalite parametresi alır, geçici indirme URL'i döner
- [ ] yt-dlp ile video indirir (YouTube, Twitter/X, Instagram ve tüm desteklenen platformlar)
- [ ] Kalite seçimi: best, 1080p, 720p, 480p, audio-only
- [ ] İndirilen dosyalar için 1 saatlik TTL — süre dolunca otomatik silinir
- [ ] Geçici dosyayı indirmek için GET /files/{id} endpoint'i
- [ ] Tek sabit API key (env config üzerinden)
- [ ] Coolify'a deploy edilebilir Docker image

### Out of Scope

- Kalıcı video depolama — servisin amacı geçicilik, depolama değil
- Kullanıcı girişi / oturum yönetimi — API key yeterli
- Çoklu API key yönetimi — tek key, tek kullanıcı
- Dashboard / admin arayüzü — saf API servisi
- Webhook / async job polling — sync download, sonuç hemen döner
- Rate limiting — özel servis, rate limit gereksiz

## Context

- **Kullanım senaryosu:** iOS Shortcuts ile entegrasyon — Shortcut video URL'ini POST eder, dönen download_url'den dosyayı indirir, Fotoğraflar veya Dosyalar uygulamasına kaydeder
- **Deployment:** Coolify (self-hosted, Docker-based)
- **Kütüphane:** yt-dlp — aktif bakımlı, geniş platform desteği
- **Geçici depolama:** Container'ın local disk'i (örn. /tmp/videos) — kalıcı volume gereksiz, container yeniden başlayınca temizlenir

## Constraints

- **Tech Stack:** Python + FastAPI — yt-dlp ile native entegrasyon, async destek
- **Auth:** Tek sabit API key, HTTP header ile (X-API-Key)
- **Storage:** Local temp disk, 1 saat TTL, background job ile temizleme
- **Deployment:** Docker container, Coolify uyumlu

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|-|
| Sync download (POST bekler) | iOS Shortcuts için 2-adım daha kolay; async polling Shortcuts'ta karmaşık | — Pending |
| JSON response ({download_url, expires_at, filename}) | Shortcut JSON parse edip URL'den indirir | — Pending |
| yt-dlp | En kapsamlı platform desteği, aktif bakım | — Pending |
| 1 saatlik TTL | Kısa vadeli kullanım, disk alanı verimli | — Pending |
| Tek API key (env) | Sadece kişisel kullanım, basitlik öncelikli | — Pending |

---
*Last updated: 2026-03-09 after initialization*
