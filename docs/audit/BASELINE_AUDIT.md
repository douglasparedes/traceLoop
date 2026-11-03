# TraceLoop — Baseline Audit (Phase 0, Gate 0)

- **Date:** 2026-11-03 · **Branch:** `guide-formats-muse-image` · **HEAD:** `e33efb7` ("improvements workbench and procedures")
- **Working tree:** clean. Audit reference `9b88691` is **not** in this clone's history; HEAD `e33efb7` already contains the finalized-then-synced workbench/procedures stabilization (finalize endpoint, JobView frontier model, sync-first finish).
- **Stack:** FastAPI + SQLite (SQLAlchemy, no Alembic — `Base.metadata.create_all` + inline additive migrations), React 18 + Vite PWA, IndexedDB offline queue, Remotion 4 SSR (`video/`), Meta AI (Voice/Spark/SAM 3.1/Image, key-gated with labelled fallbacks).

## Architecture (verified in code)

- **Capture → AI → procedure → visual guide → review → library → workbench execution → feedback → new revision.** Single pipeline; no competing workflows.
- **Jobs:** `JobSession(status)` + immutable `JobEvent`s (`event_id` unique). Canonical projection rebuilt server-side in `_project_job_state` (`main.py`); `POST /jobs/{id}/finalize` is atomic (step + finish, server-computed outcome); `POST /jobs/{id}/finish` is a legacy compat path. `POST /sync/events` dedupes by `event_id`, rejects unknown types and writes to finished sessions.
- **Offline:** IndexedDB queues `pending-regs/photos/events/finishes`; `runSync` syncs regs → photos → events → finishes with dependency waits; `pendingCounts()`/`pendingForJob()` cover all queues.
- **Media:** `MEDIA_ROOT` volume abstraction (`storage.media_path`, traversal-safe); reads/writes standardized except frontend-dist serving (code location, correct as-is).
- **Versions:** drafts/rejected/pending_review/approved/superseded with server-side transition guards; jobs pin `procedure_version_id`; approved versions immutable (PUT 409).

## Revalidation of the 12 prior findings vs HEAD e33efb7

| # | Prior finding | Status at HEAD |
|---|---|---|
| 1 | Final step needs complete + separate Finish | **Fixed** — one `Finish job ✓` action calls atomic `/finalize` |
| 2 | Blocked treated as terminal, progression continues | **OPEN (design conflict)** — blocked counts as terminal for the frontier, so Next skips past it. Master spec requires halt. Needs Phase 1 redesign (exceptional close as separate action) |
| 3 | Workbench points at wrong step on resolve | **Partially fixed** — viewIdx resets to frontier, but initial view targets frontier, skipping a blocked step. Needs blocked-first landing |
| 4 | Online/offline finalize use different rules | **OPEN** — `/finish` has no coverage check; offline path relies on it. Unify via shared rules |
| 5 | Evidence after finalize unreconcilable | **OPEN** — `POST evidence` 409s on finished jobs; pending photos for finished jobs stuck |
| 6 | Processing filter only `transcribing` | **OPEN (verified)** — `TutorialLibrary` sends `status=transcribing` only; backend has no `processing` group |
| 7 | Recording review auto-uploads | **OPEN (verified)** — `rec.onstop` calls `uploadRef.current(blob)` immediately |
| 8 | Studio dirty-state sticks | **OPEN (verified)** — `onDirty()` is one-way `setDirty(true)` for Overview/Content tabs |
| 9 | Library pagination sliced client-side | **OPEN (verified)** — `limit=100&offset=0` always; `slice(0, shown)` locally; backend supports real pages |
| 10 | Backend CI fails 3 tests incl. 2 Remotion | **Mechanism confirmed** — `video/bundle` is gitignored and CI installs no video deps and no Node in the backend job; with Node present (ubuntu runners ship it) the 2 real-render tests fail at on-demand bundling. 3rd failure unconfirmed without a CI log; hardening covers all paths |
| 11 | Weak end-to-end verification | **OPEN** — no browser E2E framework in repo |
| 12 | Inconsistent guided experience | **Partial** — primary action + labels standardized; needs completion pass |

## Baseline test results (pre-change, local)

- Backend: `162 passed, 1 skipped` (`backend/.venv/Scripts/python -m pytest backend/tests -q`) — includes 9 job-lifecycle tests, real Remotion SSR tests (Node 24 + vendored bundle present locally).
- Frontend: `105 passed` → now `115 passed` with JobExecution/sync suites (`npx tsc --noEmit` clean, `npm run build` succeeds).
- Video: `node --test asset-server.test.mjs` 5/5, `tsc -p .` clean.
- Not run here: browsers, devices, production deployment.

## Security / hygiene (read-only inspection)

- `goalkings.jks` (2750 bytes, committed in `6d79d92`, referenced nowhere): magic bytes `30 82 0a ba…` = DER/PKCS#12 container — treat as Android signing material. **Do not rewrite history unilaterally**; plan is `git rm` + ignore + rotation advisory.
- Duplicate `"@remotion/cli"` entries in `video/package.json` (pinned + caret).
- Tracked build caches: root `node_modules/.vite/**` (2 files) with no root `node_modules/` gitignore rule.
- No secrets in code; demo header-auth is the documented trust boundary; media token gating is endpoint-side.

## Implementation priorities (this session)

1. Gate 1: blocked-halt redesign + exceptional close (backend + UI), blocked-first landing, single-click finalize already in place, projection extended (`can_finalize_normally`, blocking step).
2. Gate 2: `/finish` → shared finalization rules; evidence accepted post-completion (reconciled, flagged); sync coverage for finish path.
3. CI: Node + video deps + prebuilt bundle + dist artifact in backend job; duplicate dep fix.
4. Hygiene: `git rm` jks + caches, `.gitignore` additions (history rewrite NOT done — needs owner approval).
5. Tutorials: record-review confirm, `status=processing` group, real pagination, boolean dirty contract, Library next-action affordances.
6. Workbench/procedures leftovers: needs-attention grouping incl. server-side blocked jobs, hydration-guarded "continue elsewhere", draft-exists notice on detail.
7. Tests for all of the above; Playwright smoke suite wired to CI; final report + demo checklist.
