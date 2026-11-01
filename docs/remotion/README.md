# Remotion skills vendored for TraceLoop (used by the in-app video-guide pipeline)

Source: `github.com/remotion-dev/skills` — installed upstream via
`npx skills add remotion-dev/skills`. Vendored here so the exact rules the
build agent follows are pinned, reviewable, and available offline.

- **Skills version:** 4.0.539 — vendored 2026-11-01
- Upstream docs: https://www.remotion.dev/docs/ai/skills

## What's here

| File | Skill | Why we keep it |
|---|---|---|
| `saas-SKILL.md` + `saas-framework.md` + `saas-player.md` + `saas-rendering.md` | remotion-saas | App-integration architecture. `saas-rendering.md` is the basis for our render path: **plain Node.js SSR** (`@remotion/renderer`) on our long-running server, per the skill's guidance. |
| `render-SKILL.md` | remotion-render | `npx remotion render` CLI reference. |
| `markup-SKILL.md` | remotion-markup | Composition rules our `video/` project and Spark scene prompts must obey: `useCurrentFrame()` + `interpolate()` only (no CSS transitions/animations), fps from `useVideoConfig()`, `staticFile()` assets, Zod param schemas, `calculateMetadata` for dynamic duration, deterministic output. |
| `captions-SKILL.md` | remotion-captions | `Caption` JSON type (`text/startMs/endMs`) — our timed transcript segments already match this shape. |

## How TraceLoop uses them (Muse Spark in the app)

`backend/app/ai.py::plan_video_scenes` prompts Spark to emit scene plans that
obey the markup rules above (frame-exact timings, no invented motion, captions
as `Caption`-shaped JSON). `video/src/ProcedureVideo.tsx` is written against
`markup-SKILL.md` (interpolate-only animation, `calculateMetadata` duration
from props). Rendering follows `saas-rendering.md` Node.js SSR via
`video/render.mjs`, never Lambda (no AWS account needed).

Voiceover intentionally does **not** use the skill's ElevenLabs TTS path:
the video guide reuses the user's own recorded narration, cut per step with
ffmpeg ("cut it"). Narration text is stored per scene so TTS can be added
later without touching the composition.
Per-render assets (voiceover WAV, step illustrations) are served to headless
Chrome over loopback HTTP by `video/render.mjs` + `video/asset-server.mjs`
(absolute disk paths resolve to 404 against the bundle origin; canvas-drawn
images additionally require CORS headers). Never pass bare disk paths or
`file://` URLs as media `src`.
