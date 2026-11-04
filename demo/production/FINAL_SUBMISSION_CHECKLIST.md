# Submission checklist — FINAL recovery production

- [x] `demo/output/traceloop-hackathon-final-180s.mp4` — 5400 f, 180.000 s,
      1920×1080, 30 fps, H.264 yuv420p, 1 AAC track (music+SFX, no voice).
      Previous final archived as `…-PREV.mp4` (kept, not submitted).
- [x] Editable Remotion project: `demo/remotion/src/{Film,Root}.tsx` (this file's
      composition), clips/stills/audio in `demo/remotion/public/`.
- [x] Genuine source recordings: `$TEMP\traceloop_stage\shots\page@*.webm`
      (takes listed in FINAL_SHOOT_MANIFEST.md) + `demo/demostration.mp4`.
- [x] `demo/production/FINAL_CASE_TRACEABILITY.json` — canonical chain + v6 note.
- [x] `demo/production/FINAL_RECOVERY_AUDIT.md` — audit (supersedes stale docs).
- [x] `demo/production/FINAL_CUT_LIST.json` — 17 shots, frame math = 5400.
- [x] `demo/production/FINAL_STORYBOARD.md` — master timeline.
- [x] `demo/production/FINAL_MOTION_SYSTEM.md` — transitions/motion spec.
- [x] `demo/production/FINAL_HUMAN_VOICEOVER.md` — record later; no TTS in film.
- [x] Music/SFX stems: `demo/remotion/public/audio/` (music, up, ok, sync).
- [x] `demo/output/contact-sheet.png` (12 cells) + `transition-sheet.png`.
- [x] `demo/output/traceloop-hackathon-poster.png`.
- [x] `demo/production/FINAL_QA_REPORT.md` + `FINAL_JUDGE_REVIEW.md` (10/10 PASS).
- [x] `demo/production/FINAL_E2E_TRACE.md` — workflow verification table.
- [x] Code fix: `backend/app/videoguide.py` caption-collision fix (tests green);
      live video-guide v3 generated from the canonical tutorial.
- [x] Owner tasks left: record human VO into the 9 windows; re-check portal
      rules/deadlines; submit. Commit `5e42c15` + working-tree changes
      (videoguide.py, demo/production, demo/remotion, capture scripts).
