# FINAL_RECOVERY_AUDIT.md — pre-rebuild ground truth (2026-11-04, second recovery)

Supersedes stale claims in `STATUS.md`, `META_PROCESSING_EVIDENCE.json`,
`CAPTURE_MANIFEST.md`, `TRACEABILITY.md` where they conflict with the DB.
DB (`backend/fieldguard.db`) + ffprobe are ground truth; old docs are history.

## 1. Source-file state

- `demo/demostration.mp4`: 89.631622 s, 406×720 (≈29.54 fps), h264 + AAC
  stereo. SHA-256 `c61d82f5…37690d` (unchanged). 19,312,306 bytes, mtime
  11/2. Decodes cleanly. Content: home-kitchen cookie prep (ingredients,
  whisking in steel bowl, parchment-lined tray). Hands only.
- `demo/demostration-visual.mp4`: `ffmpeg -c:v copy -an` derivative, frames
  bit-identical, 15,879,378 bytes. All app uploads used this file.
- Git tree clean (`git status --short` empty); HEAD `5e42c15`.
- Backend + frontend both up (backend restarted for key pickup; frontend
  `vite --port 5173` restarted after host reboot).

## 2. Real speech availability — CORRECTED finding

- Old claim ("AAC digitally silent, peak −inf") is **wrong**.
  Measured: full-track `mean_volume −33.9 dB`, `max_volume −5.5 dB`.
- 1-second window audit (89 windows): 88/89 windows RMS −28…−64 dB; single
  hottest window t=56 RMS −27.1 dB. No window shows speech-like energy
  (−12…−20 dB RMS with syllabic modulation). Profile = room/handling noise.
- Decision **unchanged**: no intelligible narration exists → Visual-First is
  the correct route; no transcription claimed; no synthetic narration input.
  Rationale for the `-visual` derivative is also corrected: it drops a
  noise-only track (not a "silent zero-information" track); the app's speech
  gate passes on track presence, so removing the track routes honestly to
  visual-first without tripping the narrated fallback.
- Definitive pipeline proof: the canonical tutorial's `extract_audio` event
  records `has_audio: false` (upload had no audio track at all) and **zero**
  `transcribe` events exist for it — transcription never ran, never claimed.

## 3. Live Meta capabilities (key present in repo `.env`, presence-only)

- `ai.live_enabled()` true. Verified live per stage for tutorial `a15e048d`
  (all `status: succeeded`, `provider: meta`):
  - `understand:analyze_frames` — `muse-spark-1.3`, 25,314 ms, 5 frames →
    5 genuine observations, 0 steps, 0 objects + honest `missing_information`.
  - `guide:generate_guide` — `muse-spark-1.3`, 17,826 ms, 1,077 chars,
    reference manual, `simulated: 0` in snapshot.
  - 3× `guide:regenerate_guide` (trigger `format`, user-selected
    work_instruction) — `muse-spark-1.3`, 22–27 s each, `simulated: 0`.
  - Proposal v5 `b4d55152` — `simulated: False, model: muse-spark-1.3`,
    `job: 7e34ab30`, minimal Step-2 instruction change, medium confidence.
- Live Voice (transcribe) and live SAM **never executed** for this case —
  correctly so (no speech; no objects). `segmentation_results` table is
  globally empty (0 rows).

## 4. Failed / legitimately-skipped stages (not defects)

- `extract_audio: skipped` — no audio track in uploaded derivative. Correct.
- `transcribe`: no events — never ran. Correct (nothing to transcribe).
- `segment`: no events — `objects == []` → pipeline correctly bypasses SAM
  (`main.py` forces skipped when guide exists but objects don't). The old
  film's "Component segmentation SKIPPED / Not run" frame was accurate.
- `draft:ensure_review_draft` — 0 steps, 0 evidence (AI genuinely found no
  steps). Expert authorship happened downstream (see §5).
- Timestamp clamping (`_clean_visual_steps`) can drop model-hallucinated
  out-of-range steps — documented behavior, not a defect; check
  `summary.dropped` when steps vanish.

## 5. Genuine artifacts available (canonical chain)

Tutorial `a15e048d` → Procedure `906db29a` → v2 `aacb11e0` (approved, 3 true
steps) → Job `7e34ab30` (finished, **pinned to v2**) → feedback (step-2
confusing + whisking-readiness question, photo + note queued offline, synced
on reconnect) → v5 `b4d55152` (live-Spark proposal, approved, latest).
Guide snapshots: 1 live reference_manual + 3 live work_instruction regens.
**Not available and must not be faked**: transcript/timed segments (none),
SAM masks (0 rows), accepted/derived visuals (`visual_assets` empty),
in-app generated video guide (`video_guides` has 0 rows for this tutorial —
the Video-tab feature exists in the app but was never run on this case; the
film must show at most the empty Video tab or omit it, never a fabricated
render).

## 6. Missing artifacts required for the film

- A generated in-app video guide for the canonical tutorial (would need
  expert run of Video-tab generation; silent source → caption-led output).
  Optional per storyboard (S5); include only if genuinely generated.
- Fresh continuous captures per §8 (all current clips are short-bounded cuts
  from older sessions; several source sessions predate the v5 approval).

## 7. Why the old edit had continuity problems

- 12 hard-cut shots assembled from 11 independently-recorded sessions;
  each clip starts mid-state (form half-filled, queue mid-scroll) and ends
  at arbitrary navigation boundaries — no shared-element anchors.
- `fill()`-instant text (authoring, feedback note) with no keystroke
  continuity; save/submit clicks cut before server confirmation renders.
- Chyrons fade after ~60 f, leaving 20–30 s holds with no motion design
  beyond a 4.5% push — static by inspection, not just by reputation.
- S8b/S8c were 1-second Ken Burns holds on still PNGs (no motion in source).
- VO-5 script claims "every one marked simulated" — false for the live
  chain; VO-4's "extra one goes in the bin" matches the older
  bcfe9e8b-chain session, not verified for the filmed a15e048d authoring
  clip (must re-inspect g4 or recapture).

## 8. Recordings: reuse vs replace

- REUSE (content verified, quality adequate): S1 source window (g1, from
  real footage), S7 mobile session (page@93dc936 — real offline queue +
  sync; needs re-trim, not re-shoot), v5 diff scroll (page@2a9ddad,
  ss≈14–18 shows the live proposal banner legibly), v5 card (page@a42eada).
- REPLACE (continuity or provenance gaps): upload (needs full
  empty-form→file→progress→done take), processing tour (re-shoot on current
  DB state), authoring (verify keystroke continuity; recapture with typed
  entry if `fill()`-instant), guide (show all three formats per runbook §2;
  current g5 shows one), review/approve (single continuous submit→approve
  take on a fresh draft if possible; current g6 is v2-era), feedback
  (continuous mark-confusing→note→submit take).
- Raw inventory: 93 files in `demo/assets/captures`, 39 webms in
  `$TEMP/traceloop_stage/shots/` — all retained; new takes get new names,
  nothing overwritten until the candidate passes gates.

## 9. Animations to discard

- Generic `Push` 1.0→1.045 on every `Full` shot (replace with
  per-scene motivated moves: shared-element source→upload match,
  evidence-reveal tracking, before/after wipe, desktop→mobile
  spatial continuity, offline→online state bar).
- `Sweep` amber bar (decorative; approval state change deserves a
  confirmation built from the real badge element, not a line).
- `Field` battery bar (keep the *idea* — connectivity state — but derive
  timing from the actual queued/synced events, not fixed f240–690).
- Chyron style (repetitive index pills); replace with scene titles that
  name the real artifact ("Tutorial a15e048d · visual-first", "Job
  7e34ab30 · pinned to v2").

## 10. Doc reconciliation (authoritative order)

1. DB + ffprobe (this file). 2. `REAL_CASE_VERIFICATION.md` (live chain —
   CORRECT). 3. `QA_REPORT.md` gates (numbers verified; 94/100 self-score
   discarded as vanity). STALE — do not cite: `STATUS.md` "no live
   inference" (§22), `META_PROCESSING_EVIDENCE.json` (pre-key baseline),
   `CAPTURE_MANIFEST.md` + `TRACEABILITY.md` (older bcfe9e8b/77eea958
   chain), `FINAL_VOICEOVER_SCRIPT.md` VO-5 "simulated" line. These get
   rewritten in Phases E/I, not patched now.
