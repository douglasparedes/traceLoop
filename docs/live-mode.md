# Live Mode (near-live SAM 3.1) — Option A

## What it is

Capture → **Live** toggle. SAM 3.1 on the Meta Model API segments whole
clips, not stateful frame streams, so Live works in chunks:

1. The browser captures frames at 6 FPS, max 512px, JPEG q0.65
   (`frontend/src/samLiveConfig.ts`).
2. Every 30 frames (~5s) are sent to `POST /api/live-session/{id}/chunk`.
3. The backend assembles an H.264 MP4 (bundled ffmpeg, faststart),
   uploads it to the Meta Files API (`purpose=user_data`), runs one
   `POST /v1/responses` with `model=sam-3.1`, `mask_encoding=one_bit`,
   `include_confidence=true`, `propagation_direction=forward`, then
   deletes the uploaded file.
4. Masks/bboxes per frame return as JSON; the client plays the captured
   frames back with SVG mask overlays while the next chunk records.
5. Tracking chains across chunks: the last tracked bbox becomes the
   next chunk's frame-0 box prompt (`meta_sam_parser.build_object_prompt`).

**Expected delay: ~5–10s for the first tracked chunk.** A clear loader
("Contacting SAM 3.1…") plus a persistent "Processing chunk…" badge and
last-chunk latency HUD make the delay explicit. This is near-live, not
real-time; true <1s tracking would need a self-hosted SAM predictor
(Option B, not implemented).

## Prompts

- **Concept:** one short noun phrase per chunk (e.g. `blue adjustment knob`).
- **Tap:** tap the object on the live preview → point prompt on frame 0.
- Concept and point/box prompts are never mixed (Meta rule). Clear mask
  resets chaining and returns to the concept prompt.

## API (server-side key only)

| Endpoint | Purpose |
|---|---|
| `POST /api/live-session/start` | Creates an in-memory session: `{session_id, token, expires_in}`. |
| `POST /api/live-session/{id}/chunk` | Multipart frames + `fps`, `prompt_text`/`prompt_x`/`prompt_y`, `reset`. Requires `X-Live-Token`. Validates/decodes every frame (Pillow), caps: 90 frames/chunk, 1 MB/frame, 75 chunks/session, 10-min TTL. |
| `POST /api/live-session/{id}/end` | Ends the session (token required). |

Sessions are single-process in-memory state (demo scope): restarting
the backend or running multiple uvicorn workers invalidates them; the
client detects the 403 and asks for a restart.

## Cost notes

SAM video is billed per processed frame (Meta docs: $0.20/1k frames,
50-frame minimum per request). At 6 FPS in 30-frame chunks you pay the
50-frame minimum per ~5s chunk ≈ $0.01/chunk, ~$0.60 per 5-minute
session at continuous chunking. Controls in place: 512px/6 FPS/q0.65,
drop-never-backlog pipeline, pause on tab-hidden, 75-chunk session cap.

## Run

Backend (`backend/.env` with `META_API_KEY`) + frontend dev as in the
README. Without a key, Live honestly reports SAM unavailable — it does
not fabricate video masks.

## Speech-driven prompts + live transcription

Say **“this is my flag”** while recording (Photo or Live): the phrase
extractor (`frontend/src/speechPrompt.ts`) fires once the phrase is
stable, sets the SAM prompt, and segments it. Typed/pasted transcripts
surface the same phrase as a confirm chip.

Narration uses the backend Muse Voice **realtime** proxy
(`WS /api/voice/realtime` → `wss://api.meta.ai/v1/asr/realtime`, PCM
24kHz via AudioWorklet) with a recording HUD (REC dot, timer, level
meter, live cumulative captions). If the WebSocket can't connect it
falls back to stop-and-transcribe. Keys stay server-side.

Backlog hardening: SAM chunk processing runs in a threadpool (never on
the WebSocket event loop), the relay paces forwarding to realtime
(<=~1s ahead), the worklet batches 100 ms frames, the client drops PCM
instead of queueing when the socket is >2s buffered, and a shadow
MediaRecorder always runs so a dead realtime stream is recovered in
full from the backup at Stop.

## SAM no-match recovery (Photo + Live)

A `no_match` is no longer a dead end: an automatic prompt-simplification
ladder runs first (`blue adjustment knob → adjustment knob → knob`),
then the recovery panel offers Muse Spark object suggestions
(`POST /api/evidence/{id}/suggest-prompts`), tap-the-object point
prompts on the photo itself, and retake guidance.

## Replay, verify & correct (recordings)

Every chunk MP4 is persisted server-side (`data/live/<recording>/`,
`live_recordings`/`live_chunks` tables). After stopping — even after a
reload — **Replay & verify recording** restores the latest recording:
chunk timeline, frame stepping/scrubbing with mask overlay synced to
the frame, Verify / Needs correction / Incorrect marking, re-segmenting
a single chunk with a new concept or a tap on the replay (original kept,
Original/Corrected toggle), and **Save this frame as photo evidence**
into a capture session. Recordings are token-guarded and deletable via
`DELETE /api/live-recordings/{id}`.

## Chunk audio + narration transcript

Live camera now requests mic audio too. Each chunk carries a timesliced
audio blob that the backend muxes as AAC into the stored MP4, so replays
have sound. Live transcription finals (with elapsed/audio-processed
timestamps) are mapped to chunks and persisted via
`POST /api/live-recordings/{id}/transcript`; the replay shows each
chunk's narration, and the full transcript is pushed back into the
Capture transcript for draft generation. If the mic is denied, Live
falls back to silent video with an explicit notice.

## Chunk deletion

In **Replay & verify**, each chunk has a deletion checkbox; use
**Delete chunk N** for one chunk or select several and **Delete
selected**. Deletion is server-confirmed (row + MP4 removed, recording
transcript rebuilt) and surviving chunks keep their original numbers.
APIs: `DELETE /api/live-recordings/{id}/chunks/{idx}` and
`POST /api/live-recordings/{id}/chunks/delete` (token-guarded).

## Speech timing

Frames and chunks carry a shared monotonic timeline
(`start_ms`/`end_ms` persisted per chunk). A spoken phrase is applied
to the chunk that was on screen when the phrase *began*: attached
before sending if possible, otherwise that same chunk is automatically
re-segmented as a correction when it returns — not silently shifted to
the next chunk. Chunk sending is a bounded sequential queue, so timing
never shifts when SAM is busy.

## Mic / live transcription troubleshooting

The realtime voice proxy paces 24 kHz PCM in 100 ms frames (any device
sample rate is resampled client-side). Meta closes with
`1008 Audio backlog too large` if audio arrives faster than realtime —
the HUD shows the actual PCM KB/s and mic sample rate; provider error
messages are shown verbatim, and a provider rejection before any
transcript automatically falls back to stop-and-transcribe.

## Test checklist (Android Chrome + desktop Chrome/Edge)

- [x] Backend: session token guard, simulated no-key path, mocked live
      parse + bbox chaining, bad-frame rejection (`tests/test_live.py`).
- [x] Live smoke (real key, synthetic moving circle): concept prompt
      tracked 30/30 frames with correct moving bbox + mask; tap point
      prompt tracked (object 1); chained chunk tracked 30/30 frames.
- [ ] Device: toggle Photo/Live without reload; Photo segment still works.
- [ ] Device: tap-track 30s+, occlusion, object exit/re-entry, camera
      switch, 3-min continuous run (memory), tab-hidden pause.
