# REAL_CASE_VERIFICATION.md — demostration case, live pipeline (FINAL)

## 1. Source probe

- File: `demo/demostration.mp4` (89.63 s, 406×720 portrait phone video,
  ~29.5 fps, 19.3 MB < 300 MB cap).
- SHA-256: `c61d82f5a95d302fc671e1de032d1cd10270934475113108d4fe60820b37690d`
- Decodes cleanly (exit 0). No rotation metadata.
- Content: home-kitchen chocolate-chip-cookie preparation — ingredient layout
  (sugar, flour, margarine, eggs, baking soda, chocolate chips), whisking in a
  steel bowl, parchment-lined tray. Hands only, no faces.

## 2. Speech / transcription decision

- Audio track (AAC stereo 48 kHz) is digitally silent: peak −inf over the full
  89.63 s. **No intelligible narration exists.**
- Decision: NO transcription claimed. Pipeline runs visual-first; the
  transcription stage stays PENDING/skipped honestly.
- No synthetic narration was created as expert input (would be deceptive).
- Derivative used for upload: `demo/demostration-visual.mp4`
  (`ffmpeg -c:v copy -an`: frames bit-identical, silent zero-information
  track removed). Rationale: the app's speech gate passes on track presence,
  and the narrated fallback fabricates speech for silent input (see §4).

## 3. Live Meta stage evidence — FINAL FILM CHAIN

Tutorial `a15e048d` ("Chocolate chip cookie preparation", visual-first):

| Stage | Model | Flag | Output |
|---|---|---|---|
| probe | — | succeeded | 89.63 s, 406×720 |
| extract_audio | — | skipped | no audio track, narration optional |
| understand | muse-spark-1.3 | **Live** (`simulated: false`) | 5 frames observed, 5 real observations, honest missing_information list |
| guide | muse-spark-1.3 | **Live** (`simulated: false`) | reference manual, no invented procedure |
| segment (SAM 3.1) | — | SKIPPED | no objects; no masks claimed |
| draft | — | succeeded | 0 steps initially; expert authors 3 true steps |

Live observations (DB `processing_events`): "Display assortment of packets,
tub and eggs on surface", "Lift brown paper bag toward camera",
"Contact small rectangular packet on surface", "Show rearranged assortment
on surface", "Present baking tray lined with paper".

Film chain (all verified in DB + on camera):
- Tutorial `a15e048d` → Procedure `906db29a`
- Expert-authored v2 `aacb11e0` (3 true steps: lay out ingredients / whisk
  mixture / line tray) → reviewer approved
- Job `7e34ab30` finished, **pinned to v2** (uses approved revision in force
  at execution time; later approvals do not rewrite history)
- Technician feedback on finished job (step 2 confusing: "how do I know when
  the mixture is ready?") + queued photo/note, synced after reconnect
- Improvement proposal v5 `b4d55152`: `simulated: False`,
  `model: muse-spark-1.3`, `job: 7e34ab30` — Step 2 instruction
  Before: "Combine the ingredients and whisk the mixture in the steel bowl
  until evenly mixed." After: "...until evenly mixed, with no dry pockets
  visible." (medium confidence, quoted verbatim in film)
- v5 **approved** (latest). v3 `ba2b8fb5` (same fix from the earlier job loop)
  superseded by the manual regen v4 fork (see warts).

Known warts (documented, not hidden):
- v1 `4b3aaaf4` approved empty (sequencing error: approved before steps were
  authored). Superseded; never shown as evidence of content.
- v4 `29a7228d` draft forked by a later manual regen; carries no proposal.
  The film's S8 uses v5 (the live-Spark proposal) and the approved v5 badge.

## 4. Expected vs produced (pre-key baseline, kept for audit)

Without a key, the deterministic fallback emits input-independent
screwdriver content (fabricated 364-char "transcript" for silent input).
Tutorials `f2908097`, `3b6fefbd`, probe tutorial `3c210b9d` captured this
state and are EXCLUDED from the film. Simulation was never presented as live.

## 5. Actual media refs

- Source: `demo/demostration.mp4`, derivative `demo/demostration-visual.mp4`
- Tutorial (film): `a15e048d`; Procedure: `906db29a`; Job: `7e34ab30`
  (pinned v2 `aacb11e0`); Proposal + approved: v5 `b4d55152`
- Keyframes (live): 0:09, 0:26, 0:44, 1:02, 1:20 (Visuals tab)
- No SAM masks exist for this case; none shown. No transcript exists; none
  shown. Title/equipment/task wording comes only from inspected frames.
- All 11 scene clips cut frame-exact from unedited Playwright session
  recordings (`$TEMP\traceloop_stage\shots\page@*.webm`); S8b shows the v5
  "Muse Spark analysis · muse-spark-1.3" banner; S8c shows the Procedure
  Library "APPROVED (REV 5)" card.
