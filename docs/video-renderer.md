# In-app instructional video renderer

TraceLoop's production video renderer lives in [`video/`](../video/), separate
from the hackathon presentation editing project. The backend starts it from
`backend/app/videoguide.py` by invoking `video/render.mjs` with validated
composition props. The production Docker build installs the pinned Remotion
packages and prebuilds the renderer bundle.

The `ProcedureVideo` composition uses canonical procedure and guide-snapshot
content. Its duration is derived from the scene props, and animation is driven
by Remotion frame time. The backend cuts scene narration from the user's source
recording when usable speech is available; for silent footage the composition
uses captions without adding a narration track. Render assets are served over
loopback HTTP for the headless browser, rather than passed as local file paths.

For local development, install the dependencies with `npm ci` in `video/`, then
use `npm run bundle` to build or `npm run render` with the props/output options
documented in `video/render.mjs`. The backend's video-guide tests cover render
props, audio behavior, MP4 validation and real renderer output. See
[`review.md`](review.md) for the current evidence and known limitations.
