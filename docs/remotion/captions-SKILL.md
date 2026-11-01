---
name: remotion-captions
description: Transcribing, displaying and animating captions
version: 4.0.539
---

All captions must be processed in JSON using the `Caption` type from
`@remotion/captions`:

```ts
type Caption = {
  text: string;
  startMs: number;
  endMs: number;
  timestampMs: number | null;
  confidence: number | null;
  pageBreakAfter?: boolean;
};
```

TraceLoop mapping: timed transcript segments `{text, start, end}` (seconds)
are converted to `Caption` (`startMs/endMs`) when building video props —
no re-transcription. Upstream transcribe/import/display guides live at
https://github.com/remotion-dev/skills/blob/main/skills/remotion-captions/.
