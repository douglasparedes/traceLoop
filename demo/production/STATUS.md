# Status report — corrective rebuild (honest)

## What was delivered

TRUE 3-minute product film: `demo/output/traceloop-hackathon-180s.mp4`
(5400 decoded frames, 180.000 s, 1920×1080, H.264+no audio), built from
genuine Playwright captures of the running app. No narration track (owner
records later against `traceloop_180s_voiceover_and_shots.md`).

## Deviations and incidents (all disclosed)

1. **Missing reference files.** `traceloop_180s_timeline.json` and
   `traceloop_180s_voiceover_and_shots.md` were not in the workspace. Rebuilt
   both from the mission brief with identical constraints (5400 f, 9 scenes,
   ≥144 s app footage, VO windows). Filenames kept for drop-in replacement.
2. **First film retired.** The ~2-minute graphics film and its docs/audio were
   removed by an external process during this session (see 4). This rebuild
   replaces it; do not confuse the two.
3. **Source clip is illustrative.** No camera operator on site; the uploaded
   20 s trainer clip is a rendered SVG-rig animation (declared in manifest).
   Every downstream screen, click, and state is the genuine app.
4. **Workspace interference.** During capture, untracked files vanished more
   than once (`backend/*.py` helpers, prior `demo/` build, one mobile webm
   whose directory entry survived without readable content). A second worker
   appears active in this repo (uncommitted source edits + new test files from
   another hand). Mitigations used: Temp staging, immediate re-capture,
   screenshot output redirected out of the synced tree. If frames look stale,
   re-run `RENDER.md` — the project is deterministic.
5. **Rehearsal side effects on server state.** Approval rehearsals advanced
   versions (v3 approved on camera, then v5). Finished job e543d5b9 remains
   pinned to v3 (API-verified). Duplicate pendings (v1/v2) and the API-created
   v4 duplicate were rejected via the app's own reject endpoint; v4 draft
   remains as a draft. All honest, all in the manifest.
6. **No `needs_tap` path.** The silent clip routes to visual-first analysis,
   which yields no tap-correction objects. Substituted the genuine expert
   correction flow; no SAM overlay was fabricated.

## Outstanding / needs owner

- Record human narration into the 11 documented windows; set `voiceoverSrc`.
- Re-check the Cerebral Valley portal for current duration/format/deadline rules.
- Keep backend running state in mind: the demo DB now contains rehearsal jobs
  (3 stale active probes + 1 harness job); harmless for submission, reset with
  a fresh DB if a live demo follows.
