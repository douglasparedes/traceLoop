# Review — claims, evidence, limitations

| Claim | Evidence | Status |
|---|---|---|
| Approved versions immutable | `PUT` returns 409; test `test_approval_requires_reviewer_and_approved_immutable` | Implemented; test run pending shell access |
| Sync is idempotent | Unique `event_id`; test resubmits and counts 1 record | Implemented; test run pending |
| Jobs only from approved versions | 409 guard; test `test_job_requires_approved_version` | Implemented |
| Approval needs reviewer role | 403 guard; same test | Implemented |
| Upload type/size limits | 415/413 checks; test covers 415 | Implemented |
| Offline job survives reload | IndexedDB job + queue; service-worker shell | Implemented; needs manual airplane-mode pass |
| Live Muse Spark / Voice / SAM 3.1 | `app/ai.py` verified contracts (Spark `/chat/completions` json_schema; Voice `/asr/transcribe` WAV; SAM `/responses` + `meta-sam-parser`); live end-to-end check `simulated: False` | **Live — falls back to labelled simulated only on provider failure / no key** |
| Production auth, rate limits, object storage | Not built (demo header auth) | **Open risk — required before any public deployment** |
| Segmentation geometry accuracy | SAM boxes in source pixels normalized + mask SVG decoded via `meta_sam_parser` | Live; zero-match returns `status: no_match` |
| Crop quality flagged, never faked | `_illustration_quality` (mask/resolution/edge/aspect/context); shown in Objects + Visuals tabs | Implemented; `test_feedback` + UI copy covered by pipeline tests |
| Field feedback validated + linked | `POST /api/jobs/{jid}/feedback` validates step IDs against pinned revision; 409 without `replace` | Implemented; `test_feedback.py` (6 tests) |
| Proposals create drafts, never mutate approvals | `POST /api/jobs/{jid}/propose-improvement` (reviewer+ only, finished jobs only); before/after in `source_evidence.proposal`; simulated path quotes technician verbatim, labelled low-confidence | Implemented; full-loop test (feedback → proposal → approve → supersede → pinning) |
| Per-stage live/simulated visibility | `GET /api/tutorial/{jid}/stages` rollup; Studio Overview summary + technical expander | Implemented; `ProcessingSummary.test.tsx`, `StudioStages.test.tsx` |
| Review shows transcript evidence per step | `transcript_segments` in `ver_out` computed from linked tutorial timing | Implemented; `test_feedback.py::test_version_carries_transcript_segments` |

Known limitations: manual page numbers are chunk-level (extraction keeps order, not exact pages); offline job start needs one prior online server start in this build (UI states this); no video tracking (deferred per spec §7.4); frontend has no automated test suite yet.

Submission risks to recheck with organizers: current official rules/deadlines, Geographic Use Policy, and model availability for the account used. This repo's compliance notes are an unofficial summary, not legal certification.
