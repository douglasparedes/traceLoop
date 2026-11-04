# Capture manifest — demostration case (final)

Source: `demo/demostration.mp4` (SHA-256 `c61d82f5…37690d`, 89.63 s, silent).
Processing variant filmed: `demo/demostration-visual.mp4`
(SHA-256 `4f9f2df2…64d1944c`, frame-identical, silent AAC track removed so the
speech gate routes to the honest visual-first branch; see
META_PROCESSING_EVIDENCE.json).

Tutorial `bcfe9e8b` (clean) → procedure `77eea958` (v1 approved → v2 approved)
→ job `fbefa6c3` (finished, pinned to v1) → feedback → proposal → v2.
Tainted rehearsals `3b6fefbd`, `f2908097` (input-independent screwdriver
fixture) are excluded from the film and kept only for audit.

| Film | Raw (demo/assets/captures/) | Content |
|---|---|---|
| S1 hook | demostration.mp4 [68,80] | real whisking/tray, portrait |
| S2 upload | real-upload-visualfirst.webm [4,24] | form, filename, progress, done |
| S3 processing | real-studio-tour.webm [4,37] | source player, per-stage provenance, keyframes |
| S4 correction | real-correction.webm [4,27] | 3 steps rewritten, 4th deleted, saved |
| S5 guide | real-guide-pickup.webm [10,32] | Reference Manual selected, generated, scrolled |
| S6 verification | real-approve-v2.webm [12,32] | v2 draft → submit → approve clicks → procedures |
| S7 offline | real-mobile-offline.webm [17,46], 390×844 pillarboxed | save → airplane → steps → photo/note → finish → reconnect → sync |
| S8a feedback | real-feedback.webm [7,15] | confusing verdict + note + submit |
| S8b proposal | real-proposal.webm [17,21] + diff still (d3-landed.png, 30 f) | confirm → navigation + before/after hold |
| S8c approval | real-approve-v2.webm [30,33] | APPROVED REV 2 library card |

Stills are genuine app pixels (not recreations): diff = proposal landing frame,
badge state = APPROVED REV 2 procedure card (also visible in S8c video).
A later manual-guide regen forked procedure v3 (draft); it postdates the filmed
approvals, changes nothing filmed, and is disclosed in TRACEABILITY.md.
All captures 2026-11-04, locally hosted app, Playwright Chromium, no secrets.
