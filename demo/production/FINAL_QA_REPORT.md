# FINAL_QA_REPORT.md — recovery production (candidate: `final-180s-v5` normalized)

## Automated gates (ffprobe on delivered `demo/output/traceloop-hackathon-final-180s.mp4`)

- Video: 1920×1080, 30/1 fps, H.264, yuv420p (limited range), faststart.
- Video stream duration `180.000000`; decoded `nb_read_frames 5400`.
- Container 180.010667 (AAC padding only; video gate exact).
- Streams: 0 video + 1 AAC audio (music bed + SFX accents). No voice track
  (`voiceoverSrc: null`, verified 2 streams total).
- Render: 5400/5400 encoded from `$TEMP\film-build` (synced tree); one transient
  browser-timeout flake on first v3 attempt, clean on retry (logged).

## Visual review (full-res spot frames, every scene + both dissolves)

- S1 hook, S2 typed upload + done button, S3 provenance + keyframes, S4 empty
  hold + real entry + save banner, S5 formats + v1/v2 honest errors + v3 ready
  + generated video playing, S6 submitted still + approve take + REV 6 card,
  S7 offline queue + sync-complete + cached beat, S8 verdicts + note + v5 diff
  hold + steps + REV 5 badge, S9 closer. Contact sheet (12 cells) + transition
  sheet (both dissolves) inspected.
- Single-case framing: S6a/S8b 2.0× punches and S8c 3.0× punch exclude
  unrelated queue/library rows (measured bounds; neighbor column clear by
  ~20 px on S8c). No knob/probe content identifiable anywhere in the encode.
- No black/frozen/duplicated frames (decode count == 5400 exact).
- Labels fade by ~95 f; never cover primary actions (checked S2a/S4/S8b).

## Factual review (every Meta/timing claim vs DB)

- "Live Spark" only where `simulated: false` (understand 25.3 s, guides,
  v5 proposal). Transcription never claimed (0 transcribe events). No masks
  (segmentation table empty). No time ranges (steps 0.0–0.0; app + VO say so).
- v5 proposal quoted verbatim (Before/After/confidence/job). v5 was approved
  then superseded by the filmed v6 approval — order disclosed in traceability;
  VO names no versions. Job stays pinned to v2 (DB).
- Scratch procedures removed via SQL (empty drafts only, logged); scratch
  tutorials stay archived as audit trail. No unrelated user data touched.

## P0 stop-condition sweep

Source valid · pipeline verified live where claimed · no fabricated
transcript/masks/steps · procedure tied to tutorial · approvals real
(DB `reviewed_by` + timestamps) · offline sync server-confirmed · proposal
genuine · captures complete · 5400 f exact. No blocker. No vanity score.

Reviewer signoff: each P0 item above is PASS with timecode/evidence in
FINAL_JUDGE_REVIEW.md (now confirmed on the full-res candidate).
