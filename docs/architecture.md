# Architecture

```
Browser PWA (React + IndexedDB + service worker)
  |  /api (key never in browser)
FastAPI backend ── SQLite (prototype; DATABASE_URL can point at PostgreSQL)
  └─ app/ai.py adapters ── Meta Model API (Muse Spark / Voice Transcribe / SAM 3.1)
```

**Trust boundaries.** All Meta calls, approval rules, upload validation, and idempotency live server-side. Demo identity uses `X-User`/`X-Role` headers — replace with real auth before any non-demo deployment (tracked in [review.md](review.md)).

**Data flow.** Capture → evidence → draft (`draft`) → submit (`pending_review`) → approve (immutable `approved`; prior approved becomes `superseded`) → job pins `procedure_version_id` → events queued locally with client UUIDs → `POST /api/sync/events` dedupes on unique `event_id`.

**State & failure handling.** Local-first: job progress + queue persist in IndexedDB before any network call; sync marks only server-acknowledged events; failures keep the queue and surface a retry. AI failure never blocks capture persistence. Simulated AI output is flagged `simulated` end-to-end (API field, DB column, UI tag).

**Offline.** Service worker caches the app shell; approved versions cache in IndexedDB via "Save for offline use". New transcription/draft/segmentation requires connectivity and says so in the UI.
