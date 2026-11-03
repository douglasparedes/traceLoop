# TraceLoop — Final Stabilization Report (Gates 0–7)

- **Date:** 2026-11-03 · **Branch:** `guide-formats-muse-image` · **HEAD before this session:** `e33efb7`
- **Scope:** master stabilization plan Gates 0–7 (baseline → lifecycle → offline/evidence → workbench/procedures → tutorials → video/media CI → UI polish → hackathon readiness).
- **Rule honored throughout:** no faked functionality, no mocked-success tests, no new third-party models, no history rewrite without approval.

## 1. Original issues (from the audit + plan)

1. Final step needed complete + a separate Finish click.
2. Blocked steps counted as terminal; execution advanced past the halt.
3. Workbench could point at the wrong step after resolving an incident.
4. Online/offline finalization used different rules (`/finalize` vs `/finish`).
5. Evidence attached after finalization was rejected (409) and unreconcilable.
6. Tutorials “Processing” filter requested only `status=transcribing`.
7. Recording review auto-uploaded while presenting a review screen.
8. Tutorial Studio dirty state stuck on once set.
9. Library pagination sliced a single 100-row fetch client-side.
10. Backend CI failed real Remotion tests (no video deps/bundle in job); static-asset test skipped without `frontend/dist`.
11. No browser E2E framework.
12. Inconsistent labels/primary actions across Workbench and Procedures.

## 2. Root causes

- **Lifecycle (2, 3):** blocked was folded into the generic terminal set, so the frontier skipped past it; the view index also targeted the frontier, landing past the blocker.
- **Finalize (1, 4):** `/finish` was a legacy blind-write path with no coverage check and a client-supplied outcome; `/finalize` enforced coverage.
- **Evidence (5):** finished-session guard rejected all writes, including the offline photos that finish last.
- **Tutorials (6–9):** single-status filter, `rec.onstop` auto-upload, one-way `onDirty()`, and `limit=100&offset=0` + local slice in two list components.
- **CI (10):** backend job installed neither Node/video deps nor the bundle, and never built the frontend the static tests probe.
- **Hygiene (12 + security):** signing key + build caches committed; duplicate dep entry; status labels varied per screen.

## 3. Files changed

| Area | Files |
|---|---|
| Backend lifecycle/evidence | `backend/app/main.py` (`_project_job_state` flags, `_do_finalize` shared core, `/finish` compat adapter, reconciled evidence), `backend/app/schemas.py` (`FinalizeJob.exceptional_close`, `FinishJob.exceptional_close`) |
| Tutorials backend | `backend/app/main.py` (`list_tutorials`: `status=processing` group, title/id/equipment/task search) |
| Workbench/Procedures UI | `frontend/src/App.tsx` (blocked-halt dock, exceptional close, sections, terminology, draft notice) |
| Tutorials UI | `frontend/src/TutorialLibrary.tsx` (processing filter, real pagination, next-action labels), `frontend/src/TutorialMode.tsx` (explicit review, past-list pagination), `frontend/src/TutorialUpload.tsx` (unchanged — already explicit), `frontend/src/TutorialStudio.tsx` (boolean dirty contract) |
| Tests | `backend/tests/test_job_lifecycle.py` (halt/exceptional/adapter/race), `test_api.py` (reconciled evidence, enforced finish), `test_feedback.py` (coverage-first fixture), `test_tutorial.py` (processing group/search/pagination); `frontend/src/JobExecution.test.tsx`, `TutorialLibrary.test.tsx`, `TutorialStudio.test.tsx`, `AppNav.test.tsx`, `vitest.config.ts` (smoke exclusion) |
| E2E | `frontend/playwright.config.ts`, `frontend/smoke/workbench.spec.ts`, `frontend/package.json` (+ `@playwright/test`), `frontend/tsconfig.json` |
| CI/repo | `.github/workflows/ci.yml` (video deps + bundle + frontend build in backend job, new `video` and `smoke` jobs), `video/package.json` (duplicate `@remotion/cli` removed), `.gitignore` (`node_modules/`, `*.jks`, `*.keystore`), untracked `goalkings.jks` + `node_modules/.vite` cache |
| Docs | `docs/audit/BASELINE_AUDIT.md`, this report |

## 4. Architectural changes

- One canonical finalization core (`_do_finalize`) serves `/finalize` and `/finish`; the outcome is always server-computed; blocked steps halt normal finalization; exceptional close is a distinct audited action with mandatory reason.
- Canonical `/state` projection extended with `blocked_step_orders`, `can_finalize_normally`, `requires_exceptional_close`.
- Post-completion evidence accepted and flagged `reconciled: true` instead of 409.
- Tutorial `status=processing` is now a server-side group (uploaded/transcribing/understanding/segmenting/illustrating/generating).
- Frontend dirty contract is boolean (`onDirtyChange(dirty)`), returning to clean on restore/save/refresh.

## 5. Database migrations

None. All persistence changes reuse existing columns/JSON extras (`reconciled_after_finish` in evidence `extra`).

## 6. API changes

- `POST /api/jobs/{id}/finalize`: + `exceptional_close: bool`; 422 on unresolved blocked steps unless exceptional with reason; no longer records a `step_completed` over an already-terminal step.
- `POST /api/jobs/{id}/finish`: same rules as `/finalize` (coverage enforced, outcome server-computed), no final-step event.
- `POST /api/jobs/{id}/evidence`: 200 + `reconciled: true` on finished jobs (was 409).
- `GET /api/jobs/{id}/state`: + `blocked_step_orders`, `can_finalize_normally`, `requires_exceptional_close`.
- `GET /api/tutorial`: `status=processing` group; `q` matches title, id, equipment, task description.

## 7. UI/UX changes

- Frontier holds on blocked steps; dock shows halt notice + Resolve; Skip disabled with reason; exceptional close is a two-step armed action in the summary.
- Workbench sections: My active work / Needs attention / Ready to start / Recently completed + job journal with standard labels (In progress, Blocked, Completed, Finished with exceptions).
- Procedures: `Start job` / `View procedure` terminology; draft-exists notice on approved detail.
- Tutorials: honest review screen (no auto-upload), Processing group filter, real offset pagination with dedupe, contextual row actions (Continue processing / Review for approval / …), Studio saved/unsaved badge follows the boolean contract.

## 8. Tests added

- Backend: blocked-halt, exceptional-close reason/ownership/audit, finish-adapter coverage + outcome override, concurrent-finalize safety, reconciled evidence, processing-group contract (13 tutorial tests).
- Frontend: halt/resume, exceptional path, next-action labels, processing-group request, pagination dedupe, dirty reset, Workbench sections.
- E2E (Playwright, CI): scenarios A (finish), B (block/resolve/finish), C (offline queue/reconnect).

## 9–10. Results

| Suite | Result (this session, local) |
|---|---|
| Backend `pytest backend/tests` | **167 passed, 1 skipped** |
| Frontend `vitest` | **121 passed (19 files)** |
| Frontend `tsc --noEmit` / `npm run build` | clean / succeeds |
| Video `node --test` / `tsc -p .` | all passing, 0 failures / clean |
| Playwright smoke | wired to CI (`smoke` job); **not run locally** — no browser automation in this environment |

## 11. Remaining known issues

1. `goalkings.jks` history still contains the key (committed in `6d79d92`); removal from the working index + `.gitignore` is done, but **history rewrite + rotation need explicit owner approval**. Magic bytes `30 82 0a ba` indicate a DER/PKCS#12 container — treat as signing material.
2. Real-browser and production-deployment verification not performed here; covered by the new CI `smoke` job on next push.
3. Tutorial→procedure E2E (Scenario D) remains a documented manual demo (real recording + minutes of AI); CI covers pipeline stages with mocks + fixture media.
4. A full-suite frontend run under heavy parallel load showed 2× 5s-timeout flakes once; clean re-run passed 121/121.

## 12. Deployment requirements

- `META_API_KEY` set for live inference; empty = clearly labelled simulated fallbacks.
- Persistent `MEDIA_ROOT`; `frontend/dist` served by the API app (CI now builds it in the backend job).
- Node 22 + `video/` deps + `npm run bundle` before renders (CI does this; prod build must too).
- Never commit `*.jks`/`*.keystore` (ignored); signing material via coolify secrets.

## 13. Manual verification steps

1. Seed, open Workbench → Ready to start → Start job.
2. Complete steps → last step shows Finish job → one click → completion summary.
3. New job → block step 1 → assert halt (no Next/Finish) → resolve → finish.
4. Block last step → finish refused → exceptional close without reason refused → with reason closes as finished-with-exceptions.
5. Record tutorial → review screen uploads nothing until confirmed.
6. Library: Processing filter, search by equipment, Show more past 20.
7. Studio: edit title → unsaved badge → restore text → saved badge, no dialog.

## 14. Hackathon readiness

Real Meta paths (Voice/Spark/SAM/Image) are key-gated with provenance labels; deterministic fallbacks are explicitly marked. The judge demo path (capture → AI guide → review → procedures → workbench → completed job → feedback) is fully clickable with one real-data run.

## Summary table

| Feature | Before | After | Evidence |
|---|---|---|---|
| Final-step completion | two clicks | one atomic `Finalize` | `test_job_lifecycle` + JobExecution tests |
| Blocked execution | advanced past | halts; resolve resumes | backend halt test + UI halt test |
| Workbench | mixed cards/labels | sectioned, standard labels | AppNav workbench test + smoke A |
| Procedures | variant labels | Start job / View procedure + draft notice | AppNav test |
| Offline sync | split rules | shared `_do_finalize`; idempotent events | adapter + race tests, smoke C |
| Tutorials | auto-upload, fake filter/paging, sticky dirty | explicit review, group filter, real paging, boolean dirty | tutorial + library + studio tests |
| Video rendering | CI red/mocked | real deps + bundle + dist in CI; dup dep removed | video tests green locally |
| Media persistence | assumed | volume abstraction + reconciled evidence | evidence test |
| Responsive UX | inconsistent | sectioned hierarchy, empty/error states | component tests |
| Meta AI integration | mixed provenance | key-gated live vs labelled fallback | observability tests + UI badges |
