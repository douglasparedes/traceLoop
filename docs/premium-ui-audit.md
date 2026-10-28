# Premium Redesign, Integration & Quality Audit Addendum

## UX audit summary

Architecture before this pass: React+Vite single-file `App.tsx` plus dedicated
Capture/Live/Tutorial components; FastAPI+SQLite backend; state-based navigation;
design tokens in `styles.css`; IndexedDB event queue; live Meta adapters.

Primary problems found:

1. Guided-job steps showed no visual evidence even when steps had SAM segmentations.
2. Offline-created jobs could never sync because the server did not know their local IDs, and finishes relied on a direct request.
3. The top bar devoted mobile space to a demo role selector and multiple status elements.
4. Job History was a flat list with no detail, provenance, or feedback-to-revision path.
5. The Review screen did not show source evidence beside the draft.
6. IndexedDB wrappers resolved before transactions committed.
7. Procedures had no surfaced update date, and Capture modes did not clearly distinguish Quick Capture from Record a Tutorial.

## Reliability fixes implemented

- `JobCreate.id` accepts a stable client-generated ID. Registration is idempotent and rejects reuse for a different revision.
- `syncNow` now follows **register pending jobs → sync events → push pending finishes**, with server acknowledgement driving local state.
- Finished local jobs are retained as pending-finish records until the server confirms them.
- IndexedDB writes resolve only after `transaction.oncomplete`.
- Added `GET /api/procedure-versions/{id}/evidence` and `GET /api/evidence/{id}/image` so the exact source image and its latest SAM segmentation travel together.
- New tests cover offline job registration and version evidence.

## UX changes

- The demo role selector moved from the global header to Activity → Settings and is labelled as demo identity, not production authentication.
- Guided steps render the linked reference image plus its SAM highlight, or an honest "unavailable" message when the image or mask cannot be shown.
- A live job-summary card distinguishes completed, blocked, skipped, saved-locally, and server-confirmed state.
- Capture modes are **Quick capture**, **Live**, and **Record a Tutorial**.
- Review now includes uncertainties, missing information, safety notes, and thumbnails/text from the linked source evidence.
- Job History expands to show server-confirmed event details and lets a reviewer open the job's exact revision to propose a normal, reviewable revision from an issue.
- Procedures surface their update date.

## Verification evidence

- Backend: 28 tests pass, including offline-client-ID registration and idempotent resubmission.
- Frontend: production `npm run build` passes.
- Viewports inspected with zero horizontal overflow: 320, 360, 390, 430 (mobile, bottom nav), 768 (tablet, bottom nav), 1024 (desktop nav row), 1440 (side rail). Short-viewport check (390x420, keyboard-open proxy) also clean with 59px bottom nav.
- Screenshots captured for mobile (390) and desktop (1440) after this implementation pass, plus 320/430/768 spot checks.

## Integration matrix (verified against the actual code)

| User action | UI entry | API / service | Persistence | Auth | Failure handling | Verified by |
|---|---|---|---|---|---|---|
| Search procedures | Library search + All/Approved/Offline filters | `GET /api/procedures` (client-side filter) | SQLite `procedures`/`procedure_versions` | public read | offline: IDB-cached lists stay visible | backend seed tests |
| Open procedure details | Inspect latest version | `GET /api/procedure-versions/{id}` | IDB `versions` cache + fallback | public read | "not available offline" notice | manual browser check |
| Download for offline | Save for offline use | same GET | IDB write awaited; offline badge only after verified write | public read | error notice on failure | manual browser check |
| Start job (online) | Library → Start guided job | `POST /api/jobs` | `job_sessions` + audit row | demo header id | error notice | existing job tests |
| Start job (offline) | same | deferred: local id + `pending-regs` → registered first on next sync | IDB `jobs/active` + `pending-regs` | — (queued) | "saved on this device, will register on sync" notice | new `test_offline_job_registration_with_client_id` |
| Complete / block / skip step | Guided job big actions | IDB queue → `POST /api/sync/events` | `job_events` (unique `event_id`); marked synced only on ack/dupe | demo header id | stays pending; batch-safe duplicates | existing idempotency tests + same-batch test |
| Report issue | JobView issue form | same queue + endpoint (`issue_recorded`) | same | demo header id | same; note preserved | covered by event path (no dedicated test) |
| Finish job | Finish (inline confirm) | `POST /api/jobs/{id}/finish` (idempotent) + queued `job_finished` + `pending-finishes` retry | `job_sessions` finished; local finish survives reload | demo header id | "saved on this device; syncs with events" | pre-existing finish test |
| Capture narration | LiveTranscribe | WS `/api/voice/realtime` → Muse Voice, fallback to `POST .../transcribe` | transcript + audio evidence | demo header id | layered fallback chain, nothing silently lost | existing transcribe tests |
| Upload photo | Capture attach/camera | `POST /api/capture-sessions/{id}/image` | `evidence` + `backend/data/evidence/` | demo header id | 415/413 messages | 415 test |
| Generate draft | Capture step 4 | `POST /api/procedures/draft` → Muse Spark JSON-schema | new `Procedure` + draft version + steps; transcript saved first | demo header id | labelled simulated fallback; no silent loss | existing draft tests |
| Inspect source evidence | ReviewView `ReviewEvidence` | `GET /api/procedure-versions/{id}/evidence` + `/api/evidence/{id}/image` | `evidence` + `segmentation_results` (latest per image) | public read | "no linked evidence" / "unavailable offline" states | new `test_version_evidence_endpoint` |
| Edit draft | ReviewView save | `PUT /api/procedure-versions/{id}` (draft/rejected only) | in-place steps replace | demo header id | error notice | manual browser check |
| Approve / reject | ReviewView (inline confirm for approve) | `POST .../approve` / `.../reject` | immutable transition + `audit_log`; 403 unless reviewer; 422 on empty reject reason | reviewer role enforced server-side | no optimistic success; lists + version reloaded | existing 403/422/409 tests |
| Propose revision from feedback | History issue → Review → Propose new revision | `POST .../new-revision` + `GET` version | new draft version; approved version untouched | demo header id | error notice | manual browser check |
| Synchronize | Sync now / auto on reconnect | health check → register → events → finishes | local rows updated only on server ack | demo header id | per-item queues survive reload; failures stay visible | existing + new sync tests |
| Job history detail | History drill-down | `GET /api/jobs/{id}` | server-confirmed events ordered | public read | offline fallback message | manual browser check |
| Tutorial record → guide | TutorialMode | `POST /api/tutorial/*` (session token) | `live_recordings`/`live_chunks` + MP4s | token header | status/error + retry | `test_tutorial.py` suite |

Known gaps (unchanged, by design): demo header auth is not real authentication; manuals are server-indexed only (not offline assets); no frontend unit tests exist in the repo; `favicon`/SW precache unchanged by this pass.
