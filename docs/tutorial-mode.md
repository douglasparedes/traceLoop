# TutorialMode

Capture → **Tutorial**: record a 2–10 minute tutorial (camera + mic,
720p, in-browser `MediaRecorder`), upload it, and get back a shareable
guide. Photo and Live modes are untouched.

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
The transcript can be sent into the Photo capture flow.

## Config & cost

`frontend/src/museTutorialConfig.ts` (limits, polling) and backend
constants in `backend/app/tutorial.py` (`MAX_VIDEO_SEC=600`,
`TRACKING_FPS=6`, `CONF_THRESHOLD=0.4`). Rough cost per tutorial:
Muse Voice $0.18/audio-hour, SAM video $0.20/1k frames on the
6 FPS tracking copy (≈360 frames/min), plus 2 Spark calls.
No keys ever reach the frontend.
