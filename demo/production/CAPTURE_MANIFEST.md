# Capture manifest — genuine browser recordings, one scenario

Scenario: **Benchtop Cable Trainer BCT-1 — "Adjustment-knob check"** (same
recording, same procedure, same job, same feedback throughout). No META_API_KEY
in this environment, so every AI step ran the app's labelled deterministic
simulated pipeline. Nothing is presented as live inference.

Source footage: Playwright `record_video` (desktop 1920×1080, mobile 390×844
CSS pixels @2x), Yoga-style `channel="chrome"` system Chrome, local app
(backend :8000 + frontend :5173, commit d5c463a + concurrent working-tree
changes — see status report). Toasts, banners and badges are the app's own.

| # | File (demo/assets/captures/) | Real feature / UI component | Recording date | Live / simulated |
|---|---|---|---|---|
| 1 | session-upload-flow.webm | Tutorials: recorder idle, upload form, file select, Upload & generate guide, processing progress, Open in Studio | 2026-11-03 | N/A (UI) + simulated pipeline |
| 2 | s2.mp4 (cut [0,25]) | same as 1, film scene S2 | — | same |
| 3 | page@a6cd…webm (staged Temp) | Studio Overview: source player, task description, per-stage AI processing (COMPLETED/Simulated muse-spark-1.3, PENDING, SKIPPED) | 2026-11-03 | simulated stages, labelled |
| 4 | page@3716078475…webm | Studio Content: corrected steps, "Canonical steps saved" toast | 2026-11-03 | genuine expert edit |
| 5 | page@f35ee547…webm | Content edit → Guide (Illustrated Work Instruction, regenerate, version history) → Review draft → submit → reviewer Approve → APPROVED v3 → Procedures | 2026-11-03 | genuine; simulated guides labelled |
| 6 | sessionC-offline-job.webm | Mobile Procedures → APPROVED card → "Saved for offline use" → Start job → airplane ON → steps → photo queued → field note → Finish → reconnect → Activity "Synchronization complete", 0 pending | 2026-11-03 | genuine offline queue + server ack |
| 7 | s7.mp4 (cut [12,42]) | same as 6, film scene S7 (pillarboxed 500×1080, uncropped) | — | same |
| 8 | page@37d0c0ca…webm | Activity job detail: event history, field photo, feedback (Step 2 confusing + "Knob label is not visible from this angle.") → Submit | 2026-11-03 | genuine |
| 9 | page@149c1099…webm | Create improvement proposal (confirm dialog) → lands in Review on v5 draft with before/after + "simulated analysis (no Meta key)" | 2026-11-03 | genuine; proposal simulated, labelled |
| 10 | page@8464da8e…webm | v5 draft review → submit → approve → v5 APPROVED → Procedures (APPROVED REV 5, COMPLETED) | 2026-11-03 | genuine |
| 11 | trainer-clip-20s.mp4 | Illustrative source clip (rendered SVG rig + slow zoom, silent 20 s) uploaded as the tutorial recording | 2026-11-03 | **illustrative input**, declared; all downstream UI genuine |
| 12 | trainer-clip-20s-b.mp4 | Same rig, different zoom (fresh bytes → full pipeline re-run for S2) | 2026-11-03 | illustrative input, declared |
| 13 | trainer.png | Source still + field photo attached during offline job | 2026-11-03 | illustrative input, declared |

Raw Playwright webms (page@*.webm) are kept as originals; s*.mp4 are
frame-exact editorial cuts (no content alteration). Screenshots (s1-*, ab-*,
c2-*, d*) are verification stills from the same sessions.

## What was NOT available (and therefore NOT shown)

- `needs_tap` object correction: visual-first analysis produced no `needs_tap`
  objects (silent illustrative clip → speech gate → visual-first, per
  runbook §1b). Substituted with the genuine expert step-correction flow,
  which is the same correction guarantee (ambiguous output fixed by a human
  before approval). No SAM box was fabricated.
- Live Meta inference: no API key; all simulated outputs carry the app's own
  Simulated labels.
- Narrated recording: no human narrator on site; recorder shown idle, upload
  path used (a supported first-class flow per demo-runbook).
