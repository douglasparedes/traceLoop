# E2E_TRACE.md — one connected case, tutorial → approval → job → feedback → approval

Isolated dataset: exactly one film case. Rehearsal/probe tutorials
(`f2908097`, `3b6fefbd`, `3c210b9d` LIVE probe, knob cases) archived or
excluded; they never appear in the film.

## Chain

1. **Upload (visual-first)** — Tutorial `a15e048d`
   "Chocolate chip cookie preparation" from `demo/demostration-visual.mp4`
   (frame-identical derivative of `demo/demostration.mp4`).
   Proof: `shots/page@16b1eaf*` (upload + genuine progress), S2a/S2b.
2. **Live Meta processing** — `understand` + `guide`, `muse-spark-1.3`,
   `simulated: false` (DB `processing_events`). Transcription PENDING
   (silent source, honestly labelled); segmentation SKIPPED (no objects).
   Proof: `shots/page@bb99236*` tour (stages, Visuals keyframes
   0:09/0:26/0:44/1:02/1:20), S3; `REAL_CASE_VERIFICATION.md` §3.
3. **Author + save** — expert rewrites untitled draft into 3 true steps
   (ingredients / whisk / tray), Save steps → draft v2 `aacb11e0`.
   Proof: `shots/page@c521b15*`, `liveA-steps.png`, S4.
4. **Guide** — Illustrates Work Instruction chosen, Generate/Regenerate;
   v4 fork disclosed (manual regen, no proposal).
   Proof: `shots/page@2490707*`, `freshG-guide.png`, S5.
5. **Review → approve v2** — reviewer submits + approves.
   Proof: `shots/page@f98030b*`, `liveA-approved.png`, S6.
6. **Field execution (offline)** — Job `7e34ab30`, pinned to v2 `aacb11e0`,
   finished. 390×844 mobile, airplane mode, 3 steps, photo queued, note
   "Whisking in the video is brief — how do I know when the mixture is
   ready?", Finish, reconnect → server ack (0 pending).
   Proof: `shots/page@93dc936*`, `liveM-*.png`, S7.
7. **Feedback** — step-2 "confusing" + overall note submitted against
   `7e34ab30`.
   Proof: `shots/page@99faac1*` (ss 7–15), `liveF-filled.png`, S8a.
8. **Proposal (live Spark)** — v5 `b4d55152`, `simulated: False`,
   `model: muse-spark-1.3`, `job: 7e34ab30`: Step-2 instruction
   Before "…until evenly mixed." → After "…until evenly mixed, with no dry
   pockets visible." (medium confidence). Banner: "Field-feedback proposal
   from job 7e34ab30 … Muse Spark analysis · muse-spark-1.3".
   Proof: `shots/page@2a9ddad*` (ss 14–18), `v5hunt-diff.png`, S8b,
   `demo/capture-tools/dbv5b.py` output.
9. **Approve v5 (latest)** — reviewer submits + approves v5; Procedure
   Library shows "APPROVED (REV 5)" for the cookie case; job stays pinned
   to v2.
   Proof: `shots/page@a42eada*`, `v5card.png`, `v5b-approved.png`, S8c.

## Screenshot index (per required action)

| Action | Screenshot / clip source |
|---|---|
| Upload + progress | `fresh-stages.png`, g2a/g2b |
| Live stages | `fresh-stages.png`, g3 |
| Authored steps saved | `liveA-steps.png`, `liveA-saved.png`, g4 |
| Guide generated | `freshG-guide.png`, g5 |
| v2 approved | `liveA-approved.png`, g6 |
| Offline job + sync | `liveM-job.png`, `liveM-activity.png`, g7m |
| Feedback submitted | `liveF-filled.png`, `liveF-submitted.png`, g8a |
| v5 proposal diff | `v5hunt-diff.png`, h8b |
| v5 approved badge | `v5card.png`, `v5b-approved.png`, h8c |

## IDs (ground truth, `backend/fieldguard.db`)

- Tutorial `a15e048d-…`, Procedure `906db29a-…`
- v2 `aacb11e0` (approved → superseded by v3 chain, job pin preserved)
- Job `7e34ab30-…` finished, `procedure_version_id = aacb11e0`
- v5 `b4d55152-…` approved (latest); proposal charge:
  `simulated=False, model=muse-spark-1.3, job=7e34ab30`
