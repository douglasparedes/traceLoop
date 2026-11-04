# Shoot manifest — recovery production takes (all Playwright Chromium 1920×1080 unless noted)

Raw dir: `$TEMP\traceloop_stage\shots\page@*.webm` (never overwritten; new names
per take). Edit clips: `demo/remotion/public/clips/r*.mp4` (+ `r4hold.png`,
`vguide3.mp4`, archival `g1.mp4`, `h8c.mp4`).

| Take | Session | Content | Disposition |
|---|---|---|---|
| `dabf8a9e` 71.8 s | rec_upload.py re-shoot | full upload: mode, typed fields (select-all+type), file, progress, done | CUT r2a [8,20], r2b [61,64]. Replaces take-1 (`2c565bb`, prefill-append defect, archived with its tutorial) |
| `6028ba0a` 71.3 s | rec_tour.py | canonical tour: provenance, keyframes, content, guide, video tab | CUT r3 [18,51], r5a [53,63] |
| `e8b822c0` ~43 s | rec_gen.py | interactive format select+regen; video v1 attempt → honest error | CUT r5b via pickup take below; error state kept for audit, shown in film via `123a7543` |
| `123a7543` 35.6 s | rec_vidtab.py | Video tab: v1/v2 errors + v3 ready + inline player | CUT r5b [15,23] |
| `c521b15` 75.6 s (kept) | prior session | authoring act: empty → filled → saved + banner | CUT r4 [12,34] + r4hold still @11.5 |
| `48c73e98` 26.6 s | rec_approve6.py | v6 submit (Pending 1 proven) + approve clicks (DB-proven 13:11:50 local) | CUT r6a [14,22], r6c [22,26] |
| `27ad52ad` 29.2 s | rec_payoff.py | REV 6 approved card, search-scoped | CUT r6b [6,14] |
| `0bc424d8` 60.5 s | rec_walk.py | accidental-but-honest download → offline-cached beat; canonical job detail | CUT r7b [12,15]; job frames spare |
| `65b6f3623` 60.6 s | rec_walk.py | v6 draft detail scroll (pre-approval) | spare B-roll (superseded by approval) |
| `7d0a53b1` 60.5 s | rec_walk.py | scoped library, download beat | spare (0bc424d8 preferred) |
| `93dc936` 56.3 s, 390×844 (kept) | prior mobile session | offline steps, queued photo/note, reconnect, sync-complete | CUT r7a [28,50] scaled 500:1080 |
| `99faac1` 50.4 s (kept) | prior feedback session | verdicts, verbatim note, submit (Settings detour trimmed out) | CUT r8a [7,15] |
| `2a9ddad` 30.0 s (kept) | prior v5 session | proposal diff scroll, live banner | CUT r8b [13,20] |
| `a42eada` (kept) | prior card session | REV 5 badge | h8c (archival: true when filmed, pre-v6) |
| `videoguide-v3.mp4` | app render (fixed code) | 18.2 s captioned guide, `simulated: False` | CUT r5c [4,11] |

Pollution excluded by trim (never deleted, still in raw): knob/older-chain rows
in queue/activity lists, Settings detour, pre-fix title, `2 tutorials` footer.
Take `f98030b` (v2-era approve, polluted queue, no modal in-frame) retired in
favor of the live v6 approval. Scratch procedures `ce351778`/`6a389221`
(SQL-removed, empty drafts, logged); scratch tutorials stay archived.
