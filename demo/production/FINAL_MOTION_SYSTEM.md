# MOTION_SYSTEM (rebuild) — purpose-driven, deterministic, Remotion 4.x

Rules: `useCurrentFrame()` + `interpolate()` only (per `docs/remotion/markup-SKILL.md`);
no CSS transitions, no randomness (`Math.sin` cursor pulse is a pure function
of frame). All dissolves are overlay `Sequence`s — the 5400-frame master math
is unaffected (no `TransitionSeries` overlap accounting needed).

- **Shared-element S1→S2 (match-zoom).** S1 pushes 1.0→1.14 into the preparation;
  S2a opens at 1.06 settling to 1.0 with a 10 f overlay dissolve of its own first
  frames. Motivation: the same physical footage becomes the upload preview —
  spatial continuity across the cut. (`Hook`, `Dissolve from={350}`.)
- **Guided camera (`Shot`).** Per-shot scale + x/y pan, e.g. S8a drifts −40 px to
  follow the verdict column; S3 pushes 1.0→1.04 across the 33 s scroll so the
  long hold stays alive without obscuring text. Motivation: attention steering,
  never decoration.
- **CursorRing.** Amber ring + pulse over the field being edited during S2 typing
  and S4 entry (documented approximate positions). Motivation: the old film's
  "magical text" complaint — the eye is on the field when its value changes.
  A focus aid, not an annotation of app behavior.
- **Before/after S4.** 60 f genuine-pixel still of the empty Untitled step, then
  hard cut into the take as values appear. Motivation: readable cause→effect;
  the still is disclosed, not a recreation.
- **Desktop→mobile S6→S7.** 12 f overlay dissolve into the phone take's first
  frames. Motivation: state transition (verified local → offline device).
- **Relationship reveal S8b→S8c.** Hard cut proposal→badge (the badge IS the
  proposal's outcome); no wipe needed. S8c→S9 hard cut to static closer —
  deliberate full stop.
- **Punches (static close-ups over real pixels).** `Shot` accepts
  `punch: {s, cx, cy}` (translate-then-scale about top-left, exact centering
  math). Used 3× to keep the single-case rule without deleting rows: S6a
  2.0× on the approval detail (unrelated queue excluded, Approve zone kept),
  S8b 2.0× on the proposal diff (same), S8c 3.0× isolating the archival
  REV-5 card (badge+title+buttons fully inside, neighbor column excluded by
  ~20 px). Motivation: scoping cinematography, disclosed here — never a
  composite or recreation.
  10 f in, out at ~90 f, never covering primary actions.
- **Restraint.** No particles, no 3D, no blur, no stock, no generic AI motifs.
  The only non-app pixels: hook/closer typography over real footage, the ring,
  dissolves, labels. Phone column borders double as the offline beat's frame.

Audio: music bed 0.14 full-length; `up` (upload done), `ok` (guide + approval),
`sync` (reconnect) accents; `voiceoverSrc` null → no voice track. Stems stay
separate files in `demo/remotion/public/audio/`.
