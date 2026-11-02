# TraceLoop

TraceLoop turns a short recording of someone performing a real task into an interactive, verifiable procedure that another person can follow.

**Product loop:** Capture (video + narration) → Meta AI understanding (Muse Voice, Muse Spark, SAM 3.1, Muse Image) → **canonical structured procedure** → three guide formats (work instruction, reference manual, interactive) + optional **video guide** (MP4 cut from the user's own recorded narration, scenes planned by Muse Spark, rendered with Remotion) → expert Review & approval → **immutable approved revision** → offline field execution → new evidence and revisions.

The core guarantee: the visible guide, the structured review draft, and the approved procedure always represent the same revision. Corrections propagate; approvals never mutate.

```
Capture → AI Understanding → Canonical Procedure → Guide Formats
                                                    → Human Review → Approved Revision (immutable)
                                                                       → Offline Execution → Events sync
                                                        → corrections loop back to Canonical Procedure
```

## Run it

**Backend** (FastAPI, Python 3.12+):
```powershell
cd backend
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

**Frontend** (React + Vite):
```powershell
cd frontend
npm ci
npm run dev      # proxied to :8000 for /api
npm run test     # vitest
npx tsc -b       # typecheck
npm run build    # production PWA into dist/
```

**Single container (Coolify):** `docker build -t traceloop:test .` from the repo root; see `docs/deployment-coolify.md`. The image serves API + built PWA from one origin; SQLite lives on a volume.

## Live AI vs simulated mode

Set `META_API_KEY` for live Meta AI (Voice transcription, Spark understanding/guides, SAM 3.1 segmentation, Muse Image editing). **Without a key the app runs a deterministic simulated pipeline**: scripted transcript + understanding fixtures, real local ffmpeg processing, format-aware fallback guides, `needs_tap` objects with real diagnostic frames. Every simulated artifact is labelled `simulated: true` in the UI, snapshots, and drafts — simulation is never presented as live inference. Live failures degrade to labelled fallbacks with honest error notes, never silent substitution.

## Tests

**Single workflow: Record a tutorial.** The Tutorials destination holds the
recorder (camera + microphone, upload progress, cancellation, retry,
original video preserved) above a persistent Tutorial Library (search,
status filter, sorting, pagination, refresh, delete with confirmation).
Quick capture and Live were removed from the UI; their server APIs and
stored records are untouched. Opening a tutorial enters **Tutorial
Studio**: Overview (metadata, immutable source video, processing state,
Review draft link), Content (transcript correction with the original
preserved, timed segments, structured step CRUD/reorder/tools/object
links, content revision history with restore), Guide (format change,
regenerate, immutable snapshot history with view/compare, draft
link), Video (scene plan editing with validated audio ranges and
visual choice, versioned MP4 renders with per-version preview/download),
Visuals (VisualStudio improve/highlight/alternative/annotate with
accept/reject and provenance).

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest tests -q   # 65 passed, 1 skipped
cd frontend; npm run test                                    # 58 passed
```

Key suites: `test_canonical.py` (simulated end-to-end without network, correction propagation, regen/approval/pinning, fallback distinctness, intent shaping), `test_guides.py` (formats, versions, visuals), `test_observability.py`, `test_auth.py` (incl. media-gate exemptions), `test_tutorial.py`, `test_api.py`. CI (`.github/workflows/ci.yml`) runs backend tests, typecheck, frontend tests, and the production build.

## Offline execution & media authorization

Approved procedures download for offline use; step completions, issues, notes, and photos queue in IndexedDB and sync idempotently. Service-worker media caching is token-bound (cache key = full URL including `?token=` bearer) and the media cache is wiped on sign-out, so one device user can never read another's cached private media. Guide illustrations and accepted visuals are cached for offline viewing; JSON API responses are never cached.

## Naming

User-facing product name is **TraceLoop**. `fieldguard.*` identifiers (DB filename, token prefix, cache keys, localStorage keys) are legacy storage keys kept for backward compatibility with installed devices — do not rename them without a storage migration.

## Docs

- `docs/deployment-coolify.md` — Coolify runbook, env vars, PWA/TWA notes
- `docs/demo-runbook.md` — reproducible hackathon demo script
- `docs/guide-generation-audit.md` — pipeline audit and gaps
- `docs/architecture.md`, `docs/decisions.md`, `docs/tutorial-mode.md`, `docs/review.md` — design records
