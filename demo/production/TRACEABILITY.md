# End-to-end traceability — demostration case

Source: `demo/demostration.mp4`
SHA-256: `c61d82f5a95d302fc671e1de032d1cd10270934475113108d4fe60820b37690d`
Processing variant actually filmed: `demo/demostration-visual.mp4`
(frame-identical, silent track removed)
SHA-256: `4f9f2df254f27e313b40073ec6f588cc98e18fb786754ebcc174023b64d1944c`

| Artifact | ID | Status | Pinned / preserved |
|---|---|---|---|
| Tutorial (clean, visual-first) | bcfe9e8b | done | source = demostration-visual.mp4 |
| Tutorial (rehearsal, mismatched fixture) | 3b6fefbd, f2908097 | done | superseded by clean; kept for audit, not featured |
| Procedure (clean) | 77eea958 | v1 superseded → v2 approved | v1 preserved; v2 from field-feedback proposal of job fbefa6c3 |
| Procedure (rehearsal fixtures) | 72e9df2a, 91fc73b5 | v1 draft each | never approved, never executed |
| Guided job (mobile, offline) | fbefa6c3 | finished/completed, 6+ events | pinned to v1 (de1ac65a) after v2 approval |
| Field feedback | step 2 confusing + whisking question | submitted, quoted verbatim in proposal | linked to job fbefa6c3 |
| Proposal | v2 draft | approved → v2 | before/after on step-2 verification notes, low confidence, simulated |
| Guide snapshots | initial + work-instruction + reference-manual | immutable, labelled simulated | regenerated, never mutated |

Version rule observed throughout: approvals never mutate; regeneration and
proposals fork new drafts; finished jobs stay pinned to the revision they ran
(API-verified: fbefa6c3 → de1ac65a after v2 approval).
