# UX Audit, Integration Matrix & Demo Runbook (2026 redesign)

## 1. UX audit — problems found → fixes implemented

| # | Problem (evidence) | Fix |
|---|---|---|
| 1 | 8-button wrapping nav; sticky topbar ate phone viewport; no mobile pattern | 4-destination bottom nav (Home / Procedures / Capture / Activity, safe-area aware, hidden during Guided Job); side nav ≥1100px; topbar compacted |
| 2 | Global banner always green `notice ok`, errors indistinguishable | Typed notifications (`ok`/`error`/`info`), errors use `role="alert"` |
| 3 | No `<h1>`, no skip link, view changes left focus in nav, progress bar not a progressbar | `<h1>` brand, skip link, heading focus on view change, `role="progressbar"` + values, step card `aria-live` |
| 4 | Hidden file inputs keyboard-inaccessible | Visually-hidden-but-focusable inputs inside labelled buttons (`:focus-within` ring) |
| 5 | Transcript save overwrote the SAM photo evidence id (wrong evidence segmented); no try/catch | Separate `photoEvId`; transcript save no longer sets it; errors surfaced, text preserved |
| 6 | Capture content lost on reload / AI failure | Capture form + session/photo ids persist to `localStorage`; draft generation saves transcript first and aborts (keeping text) if that fails |
| 7 | Record before session silently discarded audio; mic kept running on unmount | Record disabled until session exists; mic/camera/recorder all stopped on unmount |
| 8 | Sync marked only `acknowledged`; server `duplicates` stayed "pending" forever; failures invisible | Duplicates now marked synced (server-acknowledged); rejected events stay pending with an error banner; auto-sync on `online` |
| 9 | Offline reload lost procedure/job lists and the active version ("kept cached state" was false) | Lists persist to IndexedDB `meta/lists`; active job's version restored from IndexedDB on load; offline-ready badge only when the version is actually in the local store |
| 10 | Finished job resurrected as "active"; finish had no confirmation; zero-step versions crashed JobView | Finished jobs clear in state + storage; inline finish confirmation with completion count; zero-step guard; `POST /jobs/{id}/finish` is idempotent server-side |
| 11 | Review queue was truncated UUID chips (max 8, indistinguishable); approve shown to technicians; rejection needed no reason; rejected versions were a dead end | Queue shows title · version · status (all items); approve/reject gated by role in UI **and** server; rejection requires a comment (UI + `422`); rejected versions can be edited and resubmitted |
| 12 | Segmentation overlay rendered a fake trainer diagram when no photo was in-session; `no_match` results could be "confirmed" | Fake diagram removed (explicit "photo not in this session" state); server stores SAM `result_status` and returns `409` on confirming a `no_match` |
| 13 | Simulated transcription wiped the stored transcript server-side | Simulated transcription never mutates the capture record; existing text is returned and preserved |
| 14 | Same-batch duplicate sync events crashed the whole batch (unique-constraint 500) | Server deduplicates within the batch; verified by test |
| 15 | Job could bind a version from a different procedure; audit rows for capture/job creation stored `NULL` entity ids | `409` on procedure/version mismatch; rows flushed before audit; health endpoint now checks the DB |
| 16 | Service worker cached 404s and returned HTML for failed asset requests; manifest had no icons (not installable) | SW v2 caches only `ok` responses, HTML fallback only for navigations; generated 192/512 icons + completed manifest |
| 17 | Manual upload validated only server-side; manuals implied offline availability | Client-side type/15 MB check; UI states manuals are server-indexed, not offline assets |

## 2. Design system summary

Tokens live in `frontend/src/styles.css:1-27`: ink/muted/line, surface layers, semantic
success/warning/error/info/offline colors (never color-only — always paired with text/tags),
SAM amber reserved for segmentation, spacing scale (4–32px), radii (8/12/16), one restrained
shadow, 48px touch targets (44px small buttons), `:focus-visible` ring, reduced-motion support.
Breakpoints: bottom nav < 900px, horizontal nav 900–1099px, side nav ≥ 1100px (230px rail,
content max 980px). Typography: system stack, h1 brand / 1.45rem h2 / 1.05rem h3, 16px base.

## 3. Screen & navigation audit

Mobile: **Home** (primary continue/start action, needs-attention only when real),
**Procedures** (search + All/Approved/Offline-ready filters + offline badges),
**Capture** (3-step indicator, device-saved form, mic/camera with specific permission errors),
**Activity** (sync state + review/manuals/settings hub + job history).
Desktop adds **Review** and **Guided job** to the side nav. Guided Job hides the bottom nav,
shows one step with a sticky-feeling action hierarchy (Complete / Blocked primary; Previous /
Next / Skip / Finish secondary with confirmation).

## 4. Backend integration matrix (real endpoints)

| User action | UI | API | Persistence | Authz | Failure handling | Verification |
|---|---|---|---|---|---|---|
| Search procedures | Library search/filter | `GET /api/procedures` (client title filter) | SQLite `procedures/versions` | Public read (demo) | Cached lists from IDB offline | pytest seed flow |
| Submit knowledge | Capture create | `POST /api/capture-sessions` | `capture_sessions` (+asset) | Header identity | Form persists locally; asset/manual 404s | pytest |
| Attach photo | Capture camera/file | `POST /api/capture-sessions/{id}/image` | `evidence` + `backend/data/evidence/` | Header identity | Type/size errors surfaced | pytest (upload validation) |
| Transcribe | Record narration | `POST /api/capture-sessions/{id}/transcribe` → Muse Voice (WAV) | transcripts + audio evidence | Header identity | Simulated never wipes text; 502 on provider error | pytest + live smoke |
| Generate draft | Capture step 3 | `POST /api/procedures/draft` → Muse Spark JSON-schema | procedure + draft version + steps, provenance in `source_evidence` | Header identity | Labelled fallback on provider failure; never auto-approved | pytest + live smoke |
| Segment | Highlight SAM 3.1 | `POST /api/evidence/{id}/segment` → SAM 3.1 `/responses` | `segmentation_results` (box+mask SVG, `result_status`) | Header identity; image-only `400` | `no_match` explicit; simulated fallback labelled | pytest + live smoke |
| Approve/reject | Review | `POST /api/procedure-versions/{id}/approve|reject` | immutable approved version + `audit_log` | Reviewer/expert role server-side `403`; reject needs reason `422` | No false success; lists reload after | pytest |
| Complete a step | Guided job | IDB queue → `POST /api/sync/events` | durable local events → `job_events` (unique `event_id`) | Header identity | Pending until server ack; duplicates acked | pytest idempotency + same-batch |
| Save offline | Library | `GET /api/procedure-versions/{id}` → IndexedDB | local `versions` store | Public read (demo) | Badge only after verified local write | manual (browser) |
| Finish job | Guided job | `POST /api/jobs/{id}/finish` | `job_sessions` outcome | Header identity | Idempotent (`already_finished`) | pytest |

Known limitation (unchanged, documented): identity is demo header auth (`X-User`/`X-Role`) —
the server enforces reviewer-only approval against that header, but this is **not** production
authentication and must not be exposed publicly. CORS is open for the local demo.

## 5. Offline verification report

Verified by code path + tests: approved versions cached in IndexedDB on open/save and readable
offline; lists restored from IDB; active job + its version restored after reload; job events
queue durably and survive reload; sync requires server acknowledgment, deduplicates by
`event_id` (including within one batch), and auto-retries on reconnect. AI (Spark/Voice/SAM)
is honestly labelled as requiring connectivity. Not verified in this pass: true airplane-mode
run on a physical phone, service-worker first-visit shell (needs a second visit to cache
hashed bundles).

## 6. AI integration report

Permitted Meta models only, all server-side (`backend/app/ai.py`): **Muse Spark 1.3**
(structured drafts + grounded Q&A, JSON-schema validated, `evidence_refs` filtered to real
evidence ids), **Muse Voice Transcribe 1.0** (browser audio converted to WAV via bundled
ffmpeg), **SAM 3.1** (`/responses`, masks decoded with `meta-sam-parser`, zero-match is a
real `no_match`). Provider failure or missing key → deterministic, clearly labelled simulated
fallback; drafts are never auto-approved and approved versions are immutable (`409` on edit).

## 7. Test results

- Backend: `.\.venv\Scripts\python.exe -m pytest tests -q` → **9 passed** (adds same-batch
  dedupe, procedure-mismatch + idempotent finish, reject-reason + resubmit, segment-needs-image
  + transcript-preservation).
- Frontend: `npm run build` (tsc + vite) → **passed**.
- Live Meta smoke (previous pass, real key): Spark draft, SAM box/mask, Voice WAV+WebM, Ask —
  all `simulated: False`.
- Visual: rendered inspection at mobile/tablet/desktop viewports via browser emulation
  (see session screenshots). Not run: physical-device airplane mode, frontend unit tests
  (no frontend test harness exists in the repo).

## 8. Demo runbook (shortest reliable path)

1. `cd backend && .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000` (loads `backend/.env` → `ai_live: true`).
2. `cd frontend && npm run dev` → open `http://127.0.0.1:5173`.
3. Activity → Settings → **Seed demo procedure** → Procedures → **Start guided job** → complete steps → Activity shows queued events → **Sync now**.
4. Capture → create session → Record (allow mic) → Use camera → Capture photo → SAM prompt → **Highlight with SAM 3.1** (live mask on your photo) → Generate draft.
5. Role (top bar) → **Reviewer** → Review → Submit/Approve flow; try approving as Technician to see the server `403`.
6. Toggle browser offline (DevTools) mid-job: steps still record, pill shows pending, reconnect auto-syncs.
