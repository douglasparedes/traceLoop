# TraceLoop demo runbook (reproducible, ~10 minutes)

All steps work **without** `META_API_KEY` (deterministic simulation, clearly labelled). Steps marked [live] need the key and network.

## 0. Start (2 min)

```powershell
cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
cd frontend; npm run dev   # open http://localhost:5173
```

Sign in with the team passphrase (or leave empty for open local mode).

## 1. Capture a tutorial (2 min)

Capture → Record a tutorial: allow camera + mic (watch the mic-level meter move while you speak), record ~20 s narrating each object ("this is my red screwdriver"), stop, Upload & generate guide. [live] Real transcription/segmentation; without a key you get the labelled simulated pipeline with timestamped segments and `needs_tap` objects.

## 2. Three formats (1 min)

Open the finished tutorial → Guide tab. The AI recommendation appears with its rationale and scores. Generate **Illustrated Work Instruction**, then change format → **Reference Manual** → **Interactive Guided Execution**. Version history keeps every generation; Compare shows old vs current.

## 3. Correct an object (1 min)

Objects tab → pick a `needs_tap` object → "Tap which one you meant" → tap the object on the video. The guide regenerates from the corrected evidence, a `tap` snapshot is recorded, and the Review draft syncs (check Review → draft steps match the guide).

## 4. Improve a visual (1 min)

Guide tab → Visuals → select an overlay → **Improve image** ("make the tip easier to see") [live]. Review the side-by-side original vs proposal and the provenance (model, intent, unverified verdict), then Accept/Reject. Annotation overlays are deterministic SVG — no AI involved.

## 4b. Generate the video guide (2 min, optional)

Guide tab → **Video guide** → Generate video guide. Muse Spark plans one scene per canonical step (or the deterministic fallback does, offline); the voiceover is cut from *your own recorded narration*, sliced per step with ffmpeg — never synthesized. The render runs in the background (polls every few seconds). When ready: play it inline, check the simulated/live badge and per-scene list, Download .mp4. The MP4 is a versioned tutorial asset — regenerating after corrections creates a new version, never overwrites the old one.

## 5. Review & approve (1 min)

Open in Review (from the tutorial or Review queue). Edit nothing or fix a summary → Submit for review → switch role to Reviewer → Approve. The version becomes immutable (editing returns 409).

## 6. Execute offline (2 min)

Library → approved procedure → Save for offline use → Start procedure. Complete a step, report an issue, attach a photo. Go offline (DevTools → Offline) — execution keeps working; events queue. Reconnect — Activity → Sync now delivers them without duplicates. Sign out wipes cached private media; queued work survives.

## What to point out to judges

- Every AI output carries provenance (live vs simulated, model, trigger); nothing fake is presented as real.
- The guide, draft, and approved version are the same canonical revision — regenerate after approval forks a new draft instead of mutating.
- Corrections propagate: tap → guide → draft → snapshot, with originals preserved.
- Optional video guides cut from the user's own voice; Spark plans scenes, never the narration audio.
