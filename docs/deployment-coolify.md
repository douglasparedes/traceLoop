# Deployment — Coolify + PWA (knowloop.online)

Single-service deployment: one container serves the API **and** the built PWA
from the same origin (`https://knowloop.online`), so the manifest, service
worker and `/api` calls share one scope. No CORS or separate frontend service.

## 1. Coolify resource setup

1. **New Resource → Application → Public Repository**
   `https://github.com/douglasparedes/traceLoop`, branch `stitch-integration`
   (Dockerfile-based build; build context = repo root).
2. **Domain**: `knowloop.online` → Coolify provisions HTTPS automatically
   (required for service workers). Point DNS A/AAAA at the server first.
3. **Health check**: path `/api/health`, port `8000`.
4. **Environment variables**:
   | Var | Value | Notes |
   |---|---|---|
   | `META_API_KEY` | your Meta key | Server-only, never in the image. Without it the app runs with labelled simulated AI. |
   | `DATABASE_URL` | `sqlite:////data/fieldguard.db` | Already the image default; set explicitly anyway. |
   | `CORS_ORIGINS` | `https://app.knowloop.online` | Optional; same-origin traffic doesn't need CORS. |
   | `APP_PASSWORD` | team passphrase | **Set this before going public.** Enables the sign-in gate; empty = open (local dev only). |
   | `SECRET_KEY` | long random string | Signs auth tokens. If unset, derived from the password — set it explicitly in production. |
   | `PORT` | _(leave to Coolify)_ | Coolify injects this (e.g. `3000`); the image's CMD and healthcheck both follow `$PORT`. Do **not** set it manually unless you also change the port mapping. |
5. **Persistent volumes** (both required, or data dies on redeploy):
   - `/data` — SQLite database.
   - `/app/backend/data` — uploaded evidence, tutorial videos, live chunks.
6. Deploy. First boot: `POST https://app.knowloop.online/api/seed` once
   (idempotent) to load the demo procedure.

### Access control (demo-grade)

With `APP_PASSWORD` set, every `/api/*` route except `/api/health`,
`/api/auth/status`, `/api/auth/login` and `/api/auth/me` requires the
`X-Auth-Token` from sign-in (30-day expiry, HMAC-signed). The WebSocket voice
proxy takes the same token as `?token=`. Identity headers (`X-User`/`X-Role`)
remain demo self-declared roles — the gate proves team membership, not
individual identity. Per-user accounts with password hashes are the planned
follow-up; until then treat all data on the public URL as shared demo data.

## 2. PWA verification

1. Open `https://knowloop.online` in Chrome → DevTools → Application:
   manifest parsed, icons listed, service worker `activated`.
2. Run the URL through [PWABuilder](https://www.pwabuilder.com/) — manifest,
   service worker and security cards should be green. The repo already ships:
   192/512 `any` + maskable icons, `screenshots` (narrow + wide, real captures),
   `categories`, `display_override`, precached app shell. The service worker
   (`public/sw.js`, v5) also runtime-caches evidence/reference images and
   tutorial/live videos (cache-first, ~120-entry cap, token URLs normalized),
   uses navigation preload for faster online navigations, and serves the
   offline-capable app shell for failed navigations — while `/api/*` JSON stays
   network-only: app data syncs via IndexedDB, so a stale cached response could
   never corrupt it. `sw.js` is served with `Cache-Control: no-store` so edge
   caches (e.g. Cloudflare) can never pin an old worker version. SW updates are
   user-approved: a waiting worker shows an "App update ready" toast and only
   activates on Reload, never mid-job.
3. Install prompt: Chrome desktop (⊕ icon) and Android (“Install app”).
   Smoke test: install → airplane mode → app opens, queued work syncs later.

## 3. Android TWA (after the site is live and PWABuilder is green)

1. PWABuilder → **Package for stores → Android (Google Play)** → generate the
   package (choose package id `online.knowloop.app` to match
   `frontend/public/.well-known/assetlinks.json`).
2. Copy the **SHA-256 certificate fingerprint** from the generated package /
   Play App Signing into `assetlinks.json`, replacing
   `REPLACE_WITH_SHA256_FINGERPRINT_FROM_PWA_BUILDER_PACKAGE`.
3. Commit, push, redeploy; verify
   `https://knowloop.online/.well-known/assetlinks.json` serves the real
   fingerprint with `content-type: application/json` (the backend forces this
   content-type for `assetlinks.json`; Android rejects `text/plain`).
   `backend/tests/test_api.py::test_assetlinks_served_as_json_for_twa_verification`
   checks serving + structure on every run and skips only the fingerprint-value
   assertion while the placeholder is present — un-skip it by pasting the key.
4. Upload the `.aab` to Play Console (internal testing track first).

## 4. Known status / accepted risks

- **Demo authentication**: identity is `X-User`/`X-Role` headers (see
  `docs/review.md`). Accepted for this demo deployment by decision — the URL
  is public, so treat all data as public. Do not store real operational data.
- SQLite on a volume: fine for single-instance demo; set `DATABASE_URL` to
  Postgres before any scale-out (multiple replicas would split-brain SQLite).
- Local `backend/.env` is excluded from git and from the Docker image
  (`.dockerignore`); the key lives only in Coolify env vars.

## 5. Local verification (already done in this repo)

```powershell
docker build -t knowloop-fieldguard:test .
docker run --rm -p 18000:8000 -v fg-data:/data -v fg-uploads:/app/backend/data `
  -e META_API_KEY= knowloop-fieldguard:test
curl http://127.0.0.1:18000/api/health   # {"status":"ok",...}
curl -X POST http://127.0.0.1:18000/api/seed
```

Verified: container `healthy`, PWA shell + manifest + screenshots + assetlinks
served, seed persists across container restart, `ai_live:false` with no key
(no key baked into the image). Lighthouse (local, prod build): Accessibility
100, Best Practices 100.
