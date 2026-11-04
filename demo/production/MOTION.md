# Motion and transition specification

All animation is deterministic Remotion (`interpolate`, `useCurrentFrame`,
`Sequence`, `OffthreadVideo`, `Img` Ken Burns). No CSS transitions, no
randomness, no wall-clock. Easing is linear-ish by design (restraint).

| Moment | Film time | Treatment | Intensity |
|---|---|---|---|
| S1 hook | 00:00–00:12 | Portrait source, slow push 1.0→1.1; chyron + headline | high |
| S1→S2 match cut | 00:12 | Same kitchen footage continues inside the app's upload preview; push direction preserved | medium |
| S2 upload | 00:12–00:32 | Gentle push 1.0→1.045 over real progress; chyron labels only | medium |
| S3 processing | 00:32–01:05 | Slow push; no fake masks (segmentation SKIPPED honestly); chyron carries provenance wording | high (content) |
| S4 correction | 01:05–01:28 | Minimal push 1.0→1.03; NO transition over the typing/deletion (judges must see the genuine interaction) | low |
| S5 guide | 01:28–01:50 | Push; format change shown by the app itself (no card tricks) | medium |
| S6 approval | 01:50–02:10 | Thin accent sweep under the approve beat (decorative, 12 f) + 2 s chyron | low |
| S6→S7 desktop→mobile | 02:10 | Straight cut with continued push-in; mobile footage is the real 390×844 capture, pillarboxed uncropped, no device chrome drawn | medium |
| S7 offline | 02:10–02:39 | Thin top signal line drains while the app shows Offline and refills on reconnect (decorative; the app's own pill/toasts are the proof) | medium |
| S8 feedback→proposal | 02:39–02:55 | Straight cuts; editorial match on the quoted technician sentence; proposal diff still holds 1 s with slow zoom; badge state holds 1 s | high (payoff) |
| S9 closing | 02:55–03:00 | Static genuine tray still, dimmed; brand typography only | low |

Scene chyrons (2 s, bottom-left, fade 8 f) name each beat; they never cover
primary controls for longer than the opening beat. No particle systems, no
glitch, no 3D, no rotation, no blur sweeps.
