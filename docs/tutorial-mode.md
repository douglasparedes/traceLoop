# TutorialMode + Tutorial Studio

Record a tutorial (camera + mic, in-browser
`MediaRecorder`), **or upload an existing MP4/WebM/MOV/MKV file** (same
endpoint, same pipeline), and get back a shareable guide - there is
currently no duration limit, so walkthroughs of any length are accepted
(processing time grows with length). Then refine everything in
**Tutorial Studio** (Overview / Content / Guide / Video / Visuals).
Tutorials live in a persistent library under the
Tutorials destination, independent of the recording phase. Uploaded
files are queued on-device first and only removed after the server
confirms persistence.

## Input modes and visual-first understanding

`POST /api/tutorial/start` accepts `mode`: `auto` (default), `narrated`,
or `visual_first`, plus optional `equipment_name`, `task_description`,
`context_notes`, and `origin` (`recorded`/`uploaded`).

- **Narrated** (previous behavior): transcription is required; silent or
  empty results fail with an actionable error, unchanged.
- **Visual-First**: narration is optional supplementary context. The
  pipeline samples timestamped keyframes and calls
  `ai.analyze_tutorial_frames` (Muse Spark multimodal chat with ordered
  JPEG frames + JSON schema; deterministic labelled fallback offline),
  producing candidate steps with `evidence_frames`, `confidence`, and
  `derivation: "visual"`. Steps flow through the same SAM segmentation,
  guide generation, draft, review, and video stages.
- **Automatic**: speech sufficiency is assessed (length, segment count,
  density); weak narration routes to visual-first while keeping any
  partial transcript as supplementary context. No-audio recordings never
  fail in auto mode.

Candidate steps are validated (timestamps clamped to duration, invalid
entries dropped with reasons in provenance) and carry uncertainties;
safety-critical details are never invented — missing evidence is an
explicit `missing_information` item for the reviewer. Studio shows the
selected strategy; visually-derived steps link to their sampled keyframes
(`GET /api/tutorial/{jid}/keyframes/{name}`).

## Pipeline (all server-side, async with progress polling)

1. `POST /api/tutorial/start` (multipart video + title, upload progress
   in the UI). Identical re-uploads return the cached finished guide.
   Uploads stream to disk in 1 MB chunks (never fully in RAM) with an
   incremental checksum, enforced 300 MB cap, atomic rename, and temp
   cleanup on every path.
2. Background job (`tutorial_jobs` table, thread worker):
   - **Transcribe** - audio demuxed with bundled ffmpeg to WAV mono
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
- **Processing visibility**: Studio Overview shows a per-stage AI summary
  (`GET /api/tutorial/{jid}/stages`, aggregated from ProcessingEvents:
  pending/running/completed/failed/skipped/needs_review with
  live/simulated/mixed mode per stage). Illustration crops carry automated
  quality flags (mask validity, resolution, edge cutoff, context) shown in
  Objects/Visuals; flagged crops stay visible with a recovery note.
- **Evidence linkage**: review drafts and approved versions embed the
  transcript segments overlapping each step (`transcript_segments` in
  `ver_out`); step illustrations, SAM overlays, and accepted visuals ride
  the existing `evidence_refs`/`visual_refs` columns. Canonical identity
  covers title, instruction, expected result, verification notes, and
  tools, so expert edits there join 3-way sync instead of being silently
  overwritten.

## Config & cost

`frontend/src/museTutorialConfig.ts` (polling) and backend
constants in `backend/app/tutorial.py`
(`TRACKING_FPS=6`, `CONF_THRESHOLD=0.4`). There is currently no tutorial
duration limit. Rough cost per tutorial:
Muse Voice $0.18/audio-hour, SAM video $0.20/1k frames on the
6 FPS tracking copy (≈360 frames/min), plus 2 Spark calls.
No keys ever reach the frontend.
