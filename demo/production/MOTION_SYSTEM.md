# MOTION_SYSTEM.md — why each move exists (Remotion 4.x deterministic)

Global rules: 30 fps, 1920×1080, hard cuts only (16-frame motivated
transitions were considered; rejected — session footage already contains
continuous scrolls/typing, so extra dissolves would obscure evidence).
All motion is `interpolate()` over frame with clamp; no randomness, no
physics, no irrelevant decoration.

- **S1 Hook (0–360): slow push 1.0→1.1.** Portrait source (406×720) is
  pillar-boxed at 609×1080, never stretched. The 10% push over 12 s draws
  the eye from ingredients to hands without cropping action; produced via
  `Push` wrapper (`useCurrentFrame` + `interpolate(f,[0,360],[1,1.1])`).
- **S2–S5, S8 (Full shots): push 1.0→1.045.** Barely-perceptible drift
  keeps static UI alive on long holds (23–33 s) while leaving text
  legible; same `Push` component, `len` = shot length. Chyron fades in
  8 f so labels never cover the first readable frame.
- **S6 Sweep (f480–525 of the shot): accent bar.** A 340×5 amber bar
  travels x −400→2000 (`interpolate(f,[480,510],…)`) then fades by f525.
  Motivation: the approval click happens mid-shot; the sweep marks the
  state change (submitted → approved) without a cutaway. Produced in the
  `Sweep` component; opacity gated by two clamped interpolations.
- **S7 Field (0–870): battery bar.** Top 6 px bar drains 100→4% over
  f240–690 (offline work) then refills f690–780 amber→green (server ack).
  `drain`/`refill` interpolations composed as `drain*(1-refill)+refill`.
  Motivation: makes invisible connectivity state visible; the refill
  coincides with the "0 pending" frame. Phone column fixed at 500 px so
  the 390×844 capture is shown uncropped (1:1 pixels vertically).
- **S9 Closer: static.** No motion — a deliberate full stop after 175 s
  of evidence; still at 0.28 opacity under centered titles.

Audio (separate stems, removable): `music.wav` bed at 0.14 volume full
length; `up/ok/sync.wav` pings at f925 (upload done), f3810 (approval),
f4590 (reconnect). Voiceover is a nullable `voiceoverSrc` prop —
rendered with `null`, so the delivered MP4 has no VO track; windows in
`FINAL_VOICEOVER_SCRIPT.md` are frame-locked for later recording.
