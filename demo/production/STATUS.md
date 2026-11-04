# Status report — FINAL (2026-11-04)

## Delivered

`demo/output/traceloop-hackathon-final-180s.mp4` — 5400 decoded frames,
180.000 s video stream, 1920×1080, H.264 yuv420p, AAC (music+SFX, no voice),
plus poster, 12-cell contact sheet, Remotion source, and all 12 required
deliverables in `demo/production/`.

## The story told (all genuine)

A real 90 s kitchen recording of cookie preparation is uploaded, processed by
the app's honestly-labelled simulated visual-first pipeline (silent clip, no
transcription claimed), corrected by an expert into 3 true steps, generated
into guides, approved by a human reviewer (v1), executed offline on a real
phone viewport with photo/note/finish/sync, fed back on, turned into a
before/after proposal, and approved as v2 — with the finished job staying
pinned to v1.

## Known limitations (disclosed, not hidden)

- No live Meta inference (no key); simulated outputs carry the app's labels.
- The silent AAC track was removed (documented derivative) to avoid a
  fabricated transcript; frames are bit-identical.
- The deterministic fallback is input-independent (screwdriver fixture); the
  two tainted rehearsal tutorials were excluded from the film.
- No SAM masks exist for this branch (segmentation SKIPPED); none fabricated.
- Two 1-second Ken Burns holds on genuine screenshots (proposal diff, badge
  state) bridge moments the live capture missed; disclosed in manifest.
- A later manual-guide regen forked procedure v3 (draft); filmed approvals
  (v1, v2) are unaffected.
- Workspace interference recurred (vanishing/cloud-flickering files, possible
  second worker); mitigations: Temp staging, stable-name archives, render from
  outside the synced tree. If anything looks stale, re-render per RENDER.md.

## Needs owner

Record human narration into FINAL_VOICEOVER_SCRIPT windows; re-check portal
rules; submit.
