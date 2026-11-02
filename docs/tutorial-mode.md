# TutorialMode + Tutorial Studio

Record a 2–10 minute tutorial (camera + mic, in-browser
`MediaRecorder`), upload it, and get back a shareable guide — then
refine everything in **Tutorial Studio** (Overview / Content / Guide /
Video / Visuals). Tutorials live in a persistent library under the
Tutorials destination, independent of the recording phase.

## Pipeline (all server-side, async with progress polling)

1. `POST /api/tutorial/start` (multipart video + title, upload progress
   in the UI). Identical re-uploads return the cached finished guide.
2. Background job (`tutorial_jobs` table, thread worker):
   - **Transcribe** — audio demuxed with bundled ffmpeg to WAV mono
     24kHz, then Muse Voice Transcribe
     (`muse-voice-transcribe-1.0`) in `ENDPOINTING` mode.
     **Muse Voice returns turn-level timestamps only**
     (`turns[].startMs/endMs`); there are no word timestamps. If turns
     are empty, the full transcript becomes one segment.
   - **Understand** — Muse Spark (`muse-spark-1.3`, JSON-schema)
     extracts objects (label + first-mentioned time, pronouns resolved)
     and steps (title, start/end, summary, objects used).
   - **Segment** — a 6 FPS / 512px tracking copy is uploaded once to
     the Meta Files API; SAM 3.1 segments each object over the
     whole clip with a prompt ladder (full label → simplified variants,
     first match wins) plus one hi-res retry for misses. Best frame combines confidence, area, and temporal support, and is
     only flagged ambiguous when the top two confidences are close
     (band: ≥0.5 auto-accept, 0.25–0.5 needs review, below → needs tap).
     Every attempt is logged on the object (attempts, prompt_used).
     Illustrations: transparent cutout + mask-overlay PNGs (bbox +20%
     padding), generated with Pillow from the SAM mask.
   - Objects below the band or still unmatched after a hi-res retry are marked
     **NEEDS_TAP**: in the guide's Objects tab, seek to the object and
     tap it on the video to re-track from your tap (tap is then treated
      as ground truth).
   - **Guide** — Muse Spark writes the final Markdown guide +
     materials list (deterministic fallback if the call fails).
3. Poll `GET /api/tutorial/{id}` (token in `X-Tutorial-Token`) until
   `done`/`error`; retry with `POST /api/tutorial/{id}/retry`.

## Guide UI

Video player with SAM bbox overlays synced to playback, tabs
**Guide | Transcript | Objects**, step cards with illustration
thumbnails and click-to-seek timestamps, transcript highlighting with
click-to-seek, and Copy Markdown / Download .md /
  Download .zip (guide + illustrations) / Print-PDF export, per-object
  attempt history, and a refresh-guide action after tap corrections.
- **Tutorial Studio** (opened from the library or the result view) is the
  editing workspace: Overview (title, equipment, task, notes — the
  original video is immutable), Content (corrected transcript +
  timed segments + canonical structured steps with reorder/tools/object
  links, saved as `tutorial_content_revisions`), Guide (format change,
  regenerate, immutable snapshot history with compare, Review draft
  link), Video (scene plan editing + versioned MP4 renders, original-voice
  cuts only), Visuals (VisualStudio integration with accept/reject and
  provenance). Content saves bump `content_revision` (optimistic
  concurrency via `expected_revision`); guides/drafts update only on
  explicit regeneration, and locked drafts fork new revisions instead of
  mutating — approved versions are never touched.

## Config & cost

`frontend/src/museTutorialConfig.ts` (limits, polling) and backend
constants in `backend/app/tutorial.py` (`MAX_VIDEO_SEC=600`,
`TRACKING_FPS=6`, `CONF_THRESHOLD=0.4`). Rough cost per tutorial:
Muse Voice $0.18/audio-hour, SAM video $0.20/1k frames on the
6 FPS tracking copy (≈360 frames/min), plus 2 Spark calls.
No keys ever reach the frontend.
