# Real case analysis — `demo/demostration.mp4` (DO NOT substitute)

- File: `demo/demostration.mp4`, SHA-256
  `c61d82f5a95d302fc671e1de032d1cd10270934475113108d4fe60820b37690d`
- Container/codec: MP4, H.264 406×720 portrait (~9:16 phone video),
  ~29.5 fps avg, 89.63 s, 19.3 MB (under the 300 MB upload cap).
- Audio: AAC stereo 48 kHz track present but digitally silent (peak −inf).
  No speech, no narration. Pipeline must take the visual-first branch;
  transcription must NOT be claimed.
- Decodes cleanly (exit 0; benign dts warnings only). No rotation metadata.

## What the video actually shows (frames inspected at 5/12/30/45/60/70/82 s)

Home-kitchen chocolate-chip-cookie preparation, evening low light, phone in
hand (mild shake). No faces; hands only.

1. Ingredient layout on a stovetop: granulated sugar ("Krištáľový cukor",
   Slovak), wheat flour ("Búza Finomliszt", Hungarian), Delma margarine tub,
   2 eggs, "Natron" (baking soda) sachet with handwritten label, "Schoko
   Tröpfchen" (chocolate chips) bag, small leavening sachet, steel mixing bowl.
2. Hand picks up the small sachet (~0:45).
3. Whisking inside the steel bowl (~1:10).
4. Parchment-lined baking tray, hand adjusting it (~1:22).

## Interpretation rules for the film

- Say only what is visible: assembling ingredients, whisking, lining the tray.
- Do NOT invent quantities, recipe steps, temperatures, times, or brand claims.
- No safety-critical operations; verification = visual checks (tray lined,
  ingredients assembled, mixture whisked). No safety instructions invented.
- Objects that matter: mixing bowl, whisk, eggs, sugar, flour, margarine,
  baking soda, chocolate chips, parchment-lined tray.
- Ambiguity to preserve: exact recipe/doses unknown; visual-first steps must
  stay observational ("observed activity"), expert correction adds only what
  the frames support.

## Tutorial identity for this case

- Title: "Chocolate chip cookie preparation" (depicts the footage).
- Equipment: "Home kitchen".
- Task description: strictly the observable actions above.
- All downstream procedure revisions, jobs, feedback and proposals must
  reference THIS tutorial/upload only.
