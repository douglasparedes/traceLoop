# TRACELOOP BASELINE AUDIT — Phase 0 Gate 0

**Date:** 2026-11-03
**HEAD:** `9b88691204ff6574c276f93b5da5599f7ce17522` (main, matches audit reference)
**Working tree:** clean at inspection start
**Scope:** revalidated all 12 claims from prior audit against current code + test runs

## 1. Current architecture (verified)

**Lifecycle:** expert capture (TutorialMode record/upload) → AI processing (`backend/app/tutorial.py:run_job`) → structured procedure + snapshots/guide → review draft → approval → procedures library → guided workbench execution (App.tsx `view==="job"`) → field evidence/feedback → new revision via propose-improvement. Preserved as single coherent flow.

**Backend:** FastAPI `backend/app/main.py` (~3500 lines), SQLAlchemy models `models.py`, `tutorial.py` pipeline, `videoguide.py` Remotion renderer, `ai.py` Meta adapters (Voice Transcribe, Spark, SAM 3.1, Muse Image), `storage.py`, offline sync `POST /api/sync/events`.

**Frontend:** React + Vite `frontend/src/App.tsx` (~2000 lines, view router: home/library/job/history/tutorials), `TutorialMode.tsx`, `TutorialStudio.tsx`, `TutorialLibrary.tsx`, `TutorialUpload.tsx`, `VideoStudio.tsx`, `sync.ts` engine, `uploadQueue.ts` chunked uploads, IndexedDB `db.ts`.

**Video:** Remotion 4.0.539 `video/` (`render.mjs` + `src/`), invoked via subprocess `_render_video()` (`videoguide.py:1285-1314`), no user scene editor.

## 2. Baseline test results (exact commands)

```
# backend (with requirements.txt installed)
cd backend && python -m pytest tests -q
=> 3 failed, 159 passed, 1 skipped (49s)

FAILED tests/test_api.py::test_assetlinks_served_as_json_for_twa_verification - 404 (frontend/dist absent in backend job)
FAILED tests/test_video_remotion.py::test_real_remotion_render_with_voiceover - RuntimeError: Video render failed (video/node_modules absent)
FAILED tests/test_video_remotion.py::test_real_remotion_render_silent - same

# frontend (node 22.23.3 — node 26 + npm 11 broken: minizlib Class extends error)
cd frontend && npm ci && npx tsc -b --force => exit 0
npm run test => Test Files 19 passed, Tests 115 passed
npm run build => built in ~3.5s, 409KB JS
```

Without `requirements.txt` deps: 30 failed (missing `imageio_ffmpeg`, `meta_sam_parser`). With deps: only the 3 CI failures remain. Matches prior audit claim.

## 3. Defect revalidation (all 12 confirmed)

| # | Claim | Current code | Verdict |
|---|---|---|---|
| 1 | Final step needs complete + separate Finish | `App.tsx:1725-1730`: `allTerminal` gate then `Finish job`; `mark("done")` then `finishFinal()`. Test `JobExecution.test.tsx:144-150` clicks Next x3 then Finish | CONFIRMED |
| 2 | Blocked treated as terminal, progression allowed | `main.py:3332` `terminal={"done","skipped","blocked"}`; `App.tsx:1330` same. `finalize` succeeds with blocked; frontier skips blocked (`frontierIdx` finds first non-terminal) | CONFIRMED |
| 3 | Workbench can point to wrong step on incident | `App.tsx:1438-1472` `recordIssue/resumeStep/saveFieldNote/attachPhoto` use viewed `step` (effectiveIdx) not frontier; comment `1338-1339` says actions target frontier but only `mark()` does | CONFIRMED |
| 4 | Online/offline finalize use different paths | Online: `POST /finalize` (`1551-1553`) with validation. Offline/sync: `POST /finish` (`sync.ts:364-401`, `main.py:3209-3220` trusts client outcome, no coverage check) | CONFIRMED |
| 5 | Failed evidence can be unreconcilable after finalize | `main.py:3189` 409 if finished; `sync_events:3377-3379` rejects all post-finish writes including `evidence_attached`. No reconciliation path | CONFIRMED |
| 6 | Processing filter only `transcribing` | `TutorialLibrary.tsx:119-126` tabs All/Ready/Processing/Failed; Processing sends `status=transcribing` only. Backend supports uploaded/transcribing/understanding/segmenting/generating. Misses 4+ active stages | CONFIRMED |
| 7 | Recording review auto-uploads | `TutorialMode.tsx:362-373` `rec.onstop` builds blob then `uploadRef.current?.(blob)` immediately. Review UI doubles as progress (`632-661`). `TutorialUpload.tsx:99-140` manual-only contrast | CONFIRMED |
| 8 | Studio stale dirty state | `TutorialStudio.tsx:99-110` parent `dirty` set via `onDirty()` event only, never receives `false` except Save; switching tabs confirms + `setDirty(false)` but `ContentEditor:338` `void baseline` dead code, no restore-to-clean on server refresh | CONFIRMED |
| 9 | Library pagination incomplete | Backend returns `{total,offset,items}` sliced (`main.py:1209-1211`). Both frontends always `limit:100 offset:0` (`TutorialLibrary.tsx:59`, `TutorialMode.tsx:241`) then slice locally (`96-98`, `618`) with `shown=20` | CONFIRMED |
| 10 | Backend CI 3 fails incl 2 Remotion | Verified above: assetlinks + 2 remotion | CONFIRMED |
| 11 | Need stronger E2E | No Playwright; only vitest component + pytest integration. No full job-blocked-offline-tutorial E2E | CONFIRMED |
| 12 | UX inconsistent | `Workbench` vs `Home`, `Finish job` vs `finished-with-exceptions` vs `Pass`, single activeJob card no Active/Blocked/Ready/Completed grouping (`App.tsx:458-619`), competing primary buttons, tiny status text | CONFIRMED |

## 4. Additional findings

- **Security P1:** root `goalkings.jks` (2750 bytes, ASN.1 JKS header, likely private Android signing key) committed. `.gitignore` ignores `*.jks`? No — must `git rm` + rotate. No secret leakage beyond this found.
- **Duplicate dep:** `video/package.json:15-16` `@remotion/cli` twice (`4.0.539` + `^4.0.539`, latter wins). Must dedupe.
- **CI gaps:** backend job has no `setup-node`, no `npm ci` in `video/`, no `frontend/dist` artifact → assetlinks + remotion fail by design. Frontend job builds but artifact discarded.
- **Revision pinning OK:** `JobSession.procedure_version_id` set once (`main.py:2930`), never mutated; draft start 409; superseded allowed only with HMAC offline grant. No change needed, only tests to lock behavior.
- **`pwaInstall.ts:62` relative fetch** `.well-known/assetlinks.json` (missing leading `/`) breaks under `/procedures`.
- **Docstring drift:** `finalize_job` docstring says `completed-with-exceptions` but code/tests use `finished-with-exceptions` (`main.py:3341-3342`).

## 5. Implementation priorities (gates)

1. **Gate 1 lifecycle:** blocked≠terminal, atomic final-step, frontier-targeted incidents, canonical projection with `can_progress/can_finalize/blocked_step`.
2. **Gate 2 offline:** single `_finalize_core`, sync uses finalize semantics, evidence reconciliation post-finish, idempotent events.
3. **Gate 3 workbench/procedures:** Active/Needs-attention/Ready/Completed grouping, consistent labels, correct blocked CTA.
4. **Gate 4 tutorials:** honest review-confirm, semantic processing filter, real pagination, dirty contract.
5. **Gate 5 video:** dedupe dep, CI installs video deps + builds frontend, keep real render tests.
6. **Gate 6-7:** design tokens/labels, Meta provenance, demo runbook, final report.

Do not stop after audit — continue to implementation.
