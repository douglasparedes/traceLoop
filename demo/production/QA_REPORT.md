# QA + timing report — TraceLoopHackathon180 (rebuild 2026-11-03)

## Hard gates

| Gate | Result |
|---|---|
| Exactly 180.000 s, 30 fps, 5400 frames | ffprobe: 180.000000 s, 30/1 fps, nb_frames 5400, **decoded nb_read_frames 5400** |
| 1920×1080, H.264 | 1920×1080, h264, yuv420p (limited range), faststart |
| No narration / no TTS / no speech | `voiceoverSrc: null` → no Audio element; audio-stream probe empty |
| Real UI dominant ≥144 s of 180 s | 4850/5400 frames = **161.7 s** genuine browser footage (see timing) |
| No black/blank transition errors | 22 boundary frames probed (all 9 cuts ±1 + ends); no blank content frames (opening/closing cards hold full opacity from frame 0 — verified after fade removal) |
| No missing files | all 9 clips decoded in render; contact sheet below |
| No mock UI | all footage is Playwright-captured Chromium @ real localhost app; graphics limited to title/end cards + 2 s scene chyrons |

## Scene timing (frame-exact, total 5400)

| Scene | Frames | Seconds | Footage |
|---|---|---|---|
| S1 opening card (graphics) | 0–300 | 10.0 | — |
| S2 capture (upload flow) | 300–1050 | 25.0 | session-upload-flow |
| S3 understanding (provenance) | 1050–1740 | 23.0 | AB studio tour |
| S4 correction (expert rewrite+save) | 1740–2460 | 24.0 | AB content edit |
| S5 guide (format+regen) | 2460–3060 | 20.0 | AB guide |
| S6 review (submit→approve v3) | 3060–3660 | 20.0 | AB review |
| S7 offline (mobile 390×844, uncropped) | 3660–4560 | 30.0 | sessionC-offline-job |
| S8a feedback (confusing+note+submit) | 4560–4770 | 7.0 | D run |
| S8b proposal (before/after) | 4770–4950 | 6.0 | D3 landing |
| S8c approve v5 + procedures | 4950–5150 | 6.67 | D4 |
| S9 closing card (graphics) | 5150–5400 | 8.33 | — |

## Red-team

- Simulated shown as live? No — app's own Simulated badges + "no META_API_KEY" notes + manifest.
- Fake SAM/objects? No object-correction shot exists (visual-first path has no `needs_tap`); substituted with genuine expert step-correction, disclosed in manifest.
- Fake phone? No — real 390×844 capture, pillarboxed uncropped, no device chrome drawn.
- Cursor/simulation fakery? All clicks are real Playwright interactions (confirm dialog accepted programmatically = same as a human click).
- Version-number continuity: v3 approved on camera; job v3-pinned (API-verified); v5 approved on camera. VO avoids hard numbers except where the UI shows them.
- App untouched? `video/` never modified; backend/frontend only exercised via UI + two API cleanup calls (rejected duplicate draft-submits, rejected stale API-created v4 duplicate).

## Self-score (honest)

Impact 26/30 · Meta AI Tooling 21/25 · Technical Depth 17/20 · Demo 23/25 → **87/100**. Deductions: simulated (not live) inference; illustrative (not camera) source clip; no object tap-correction path in this pipeline branch.
