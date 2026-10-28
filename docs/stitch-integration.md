# Stitch Integration — Implementation & Verification Record

Branch: `stitch-integration`. Visual reference: `stitch_traceloop_fieldguard_design_system.zip`
(4 screens + `DESIGN.md`). No Stitch HTML was copied; tokens and layout were
translated into the existing React/CSS/IndexedDB architecture.

## A. Summary of changes

**Design system (`frontend/src/styles.css`, `frontend/src/icons.tsx`)**
- Stitch `DESIGN.md` front-matter tokens implemented as CSS variables:
  primary `#005235`, primary-container `#236b4b`, surfaces `#f2fcf2/#ecf6ed/
  #e6f1e7/#e1ebe1/#dbe5dc`, ink `#151e18`, outline `#707972/#bfc9c0`,
  tertiary/review `#743337/#ffdad9`, info `#2563eb`, radius 8/12/16/24,
  48px touch targets, tabular numerals, reduced-motion support.
- Inter-first font stack with system fallback (no webfont dependency, offline-safe).
- New component classes: badges (triple-lock glyph+text+tint), filter tabs,
  category pills, segmented progress, action dock, bottom-sheet drawer,
  safety banner, tool pills, stat tiles, equipment select, sync pill, avatar.
- `icons.tsx`: 40+ inline SVG icons (no external font/CDN; works offline).

**App shell (`App.tsx`, `types.ts`)**
- Stitch header: logo mark, TraceLoop + per-screen label, real sync pill
  (online/pending/offline), avatar with demo-role initial.
- Bottom nav (Home/Procedures/Capture/Activity) and desktop nav with icons;
  new `detail` view; screen labels per view.

**Screens (all wired to real state)**
- Home → Operational Workbench: time greeting + date, sync ribbon (real pending
  count + real `navigator.storage` estimate), resumable active job with progress,
  action grid with real approved count, sign-off section from real review queue,
  recent work from real jobs with PASS/ISSUE/OPEN badges. No fabricated metrics.
- Library: offline banner with real cached count, real search, status tabs
  All/Approved/Downloaded/Drafts/Review with real counts, client sort
  (updated/title), dynamic category pills from `asset_type` (hidden when ≤1),
  per-status cards and actions, empty state with working Clear filter.
- Procedure Detail (new): revision badge, offline badge, AI-state tag, summary,
  prerequisites, real safety notes, tools, steps, Start / Save offline / Open in
  review. Drafts can never start a job.
- Guided Job: Stitch execution screen — back/exit, sync pill, rev badges,
  segmented progress, primary action, expected-result card, reference photo with
  real SAM overlay (or honest empty state), real safety notes, tooling, summary,
  sticky action dock (Previous / Attach Photo / Field Note / Report Blocked /
  Complete Step), issue drawer with required notes, field-note dialog,
  double-submit guards. New: job photo evidence (online upload, offline IDB
  queue, server confirm), `field_note` events (synced, shown in history).
- Capture: draft banner with real photo/word counts, equipment autocomplete
  from real `GET /api/assets`, Discard draft (local), privacy notice.
  Quick/Live/Tutorial modes preserved.
- Review/History/Manuals/Settings: reskinned, logic unchanged; history renders
  `field_note`/`evidence_attached` events and job photo thumbnails.

**Backend (`backend/app/main.py`, `tests/test_api.py`)**
- `GET /api/procedures` now includes `asset_type` (additive).
- New: `POST /api/jobs/{jid}/evidence` (image ≤8MB, JPEG/PNG/WebP, 409 when
  finished, 404/415 guards), `GET /api/jobs/{jid}/evidence`,
  `evidence` array added to `GET /api/jobs/{jid}` (additive).
- New test `test_job_evidence_attach_and_list` (attach, list, serve, finish-guard).

**Offline (`frontend/src/db.ts`, `App.tsx` syncNow)**
- IDB v1→v2 adds `media` store (photo blobs survive reload).
- syncNow: register jobs → upload pending photos (queues `evidence_attached`
  events) → sync events → push finishes. Verified over real offline emulation.

## B. Interaction wiring matrix (condensed)

| Screen · Control | Behavior | Verified |
|---|---|---|
| Header · sync pill / avatar | Real pending count, online state, role initial | Browser |
| Home · Resume / Find procedure / Capture / counts / review link / history | Real job, counts, queue item, drill-down | Browser |
| Library · search / 5 tabs / sort / category / Start / Download / Details / Review / Refresh / Clear | All change real results; downloads verified in IDB | Browser + IDB |
| Detail · Start / Save offline / Open in review | Real job start, cached write, review handoff | Browser |
| Job · Previous/Next/Skip/Complete (dedupe-guarded) | Real events, no duplicate on double click | Browser (dedupe hit) |
| Job · Attach Photo online | Upload → `evidence_attached` → thumbnail | Browser + API |
| Job · Attach Photo offline | IDB blob + pending queue → uploads on sync | Browser (offline emu) + API |
| Job · Field Note / Report Blocked drawer (required note) / Finish+confirm | Real `field_note`/`issue_recorded`/`step_blocked`/`job_finished` | Browser + API |
| Job · Ask | Real `/api/ask`, offline fallback message | Existing path |
| Job · Exit | Returns home, job resumable | Browser |
| Capture · session / camera / file / transcribe / SAM / suggest / tap / draft / discard / assets | Unchanged logic, reskinned; discard clears local form | Browser (render) + tests |
| Tutorial / Live tabs | Untouched components, mount verified | Browser |
| Review · queue / edit / submit / approve-confirm / reject-require-reason / new revision | Unchanged logic, server-enforced | Browser (render) + tests |
| History · detail drill-down incl. notes/photos, propose revision | Real server events + evidence | Browser + API |
| Activity · Sync now / Manuals / Settings incl. role, seed, cache clear, health | Real sync + endpoints | Browser |
| Sync · register → photos → events → finishes | Idempotent, ack-only marking | Browser offline E2E + tests |

**Statuses:** all above are WIRED & VERIFIED except Capture AI actions and
approve-as-reviewer, which are WIRED, NOT FULLY VERIFIED in-browser this pass
(covered by backend tests + prior live smoke per `docs/ux-audit-integration.md`).

## C. Explicit unwired/partial report

1. **QR/NFC "Quick Tag Match / Scan" (Library)** — UNWIRED/omitted. No tag→procedure
   mapping or `BarcodeDetector` flow exists; rendering it would be fake. Next:
   define tag schema + lookup endpoint, then add the pill.
2. **"Inspect 1:1" schematic modal (Guided Job)** — UNAVAILABLE. No schematic asset
   exists for procedures; reference photo renders inline instead. Next: attach
   diagram evidence per step, then add fullscreen viewer.
3. **Telemetry tiles (pressure/temp, Stitch)** — UNAVAILABLE. No sensor source in
   the data model; omitted rather than mocked. Replaced with honest sync-status
   line. Next: define telemetry ingest before displaying.
4. **"Tune" filter button (Library)** — omitted; Sort + tabs + categories cover
   filtering with real behavior. P2 cosmetic deviation, documented.
5. **Category pills** — PARTIAL: render only when >1 distinct `asset_type` exists
   (currently 1 in dev data, so hidden). Logic verified in code, not visually.
6. **Manuals offline** — unchanged limitation: server-indexed, not offline assets
   (UI states this).
7. **Demo header auth (`X-User`/`X-Role`)** — unchanged P0 risk for any public
   deployment; server enforces reviewer approval against it. See `docs/review.md`.
8. **Camera/mic hardware** — PARTIAL: permission-error paths and upload pipeline
   verified; no physical-device capture performed this pass.
9. **Approve-as-reviewer click-through** — backend-tested (403/409/422), not
   browser-exercised this pass (would mutate dev data; role gate UI verified).
10. **PWA install / first-visit shell caching** — unchanged from prior pass; build
    injects precache list (verified in build output), not re-tested on device.

## D. Test results

- Backend: `pytest tests -q` → **29 passed** (28 existing + 1 new), 1 pre-existing
  deprecation warning (anyio alias in testclient).
- Frontend: `tsc -b` clean; `npm run build` passed (precache injection confirmed).
- Browser E2E (dev servers, real backend): Journey A (find→detail→start→note→
  photo→issue→complete→finish→history→sync, 6 events + photo server-confirmed);
  Journey D (offline photo queue + step → reload → resume → sync → server has
  photo + `evidence_attached`); validation (empty issue note refused,
  double-complete refused); responsive 320/360/390/430/768/1024/1440 + 390x420,
  zero overflow, correct nav per breakpoint; console error-free.
- Not run: frontend unit tests (no harness in repo), physical-device airplane
  mode, production build serving.

## E. Security & reliability findings

- Unresolved (pre-existing, unchanged): demo header auth is not real auth; CORS
  open for local demo; no rate limiting/object storage. Must not expose publicly.
- Fixed/verified this pass: duplicates marked synced; same-batch dupe safe
  (server); finish idempotent; photo events keyed by fresh UUID (no stuck-pending
  rows); action buttons disabled while a request is in flight.
- IDB v2 upgrade is additive (existing v1 data preserved; old and new code both
  tolerate missing stores).

## F. Blockers & next steps

- P0: production auth + CORS lockdown before any non-demo deployment.
- P1: QR tag lookup; step schematic assets; reviewer click-through on staging;
  device airplane-mode pass.
- P2: tune control, telemetry ingest, frontend unit harness, category-pill visual
  with multi-type data.
