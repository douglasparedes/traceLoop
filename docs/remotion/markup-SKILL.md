---
name: remotion-markup
description: Content, animation and effects best practices
version: 4.0.539
---

Rules the TraceLoop `video/` composition obeys (abridged from upstream;
full text: https://github.com/remotion-dev/skills/blob/main/skills/remotion-markup/SKILL.md):

- Keep `useCurrentFrame()` in the smallest component that needs it. Get `fps`
  from `useVideoConfig()` for ALL seconds-to-frames calculations.
- Drive animations with `useCurrentFrame()` + `interpolate()`. **CSS
  `transition`/`animation` and Tailwind animate-* do NOT render** — refactor
  to interpolate. Prefer `Easing.bezier()` / `Easing.spring()`.
- Keep `interpolate()` calls inline in the `style` prop; prefer `scale`,
  `translate`, `rotate` CSS properties over `transform` strings.
- Media: `<Audio>` / `<Video>` from `@remotion/media`, `<CanvasImage>` /
  `<Img>` for images, `staticFile()` for bundled assets (absolute local
  paths also work in Node.js server renders).
- Deterministic output only: no `Math.random`, no `Date.now`, no CSS
  animations — every render must be byte-comparable for the same props.
- Parameterize compositions with a Zod schema (`parameters.md`); compute
  dynamic duration/dimensions in `calculateMetadata` (`calculate-metadata.md`).
- Captions: use the `Caption` JSON type (`remotion-captions` skill);
  our timed transcript segments already match `{text, start, end}`.
- Voiceover in upstream uses ElevenLabs TTS — TraceLoop does NOT: we cut
  the user's own recorded narration with ffmpeg instead.
- Fonts: upstream recommends Google Fonts, but our renders must work
  offline in the container, so the composition uses system font stacks.
- Install packages with `npx remotion add` to pin compatible versions.
