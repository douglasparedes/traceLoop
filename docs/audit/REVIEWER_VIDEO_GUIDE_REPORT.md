# TraceLoop — Reviewer Knowledge Management, Premium Video Composition & Unified Guide Design

**HEAD:** `d5c463a` + working-tree implementation (this session)
**Date:** 2026-11-03

## A. Root-cause findings

### 1. Reviewer deletion missing
- `DELETE /api/tutorial/{jid}` was token-only: any demo role with the per-tutorial token (leaked in `GET /api/tutorial` list responses) could delete. No role check, no audit row.
- Delete removed only `tutorials/{jid}/` dir + the `TutorialJob` row. Orphaned: `GuideSnapshot` (FK no cascade), `TutorialContentRevision`, `VideoGuide`, `VisualAsset`, `ProcessingEvent`, and `Evidence(source_reference=tutorial:{jid})` rows + `data/evidence/` files. No cleanup, no impact summary.
- `POST /archive` / `/unarchive` existed but had no `who` param (no role check), no UI anywhere, and `GET /api/tutorial` never sent `include_archived`, so archived items were undiscoverable. Library filter tabs were All/Ready/Processing/Failed only.
- No `DELETE` for `capture-sessions`; reviewers could not retract source knowledge.

### 2. Oversized video images
- Sources saved at native resolution (`make_illustrations` PNGs, `_extract_step_frame` full-res JPG, Muse auto-images verbatim) and served as-is (`asset-server.mjs` no resize; `rewritePropsForRender` only rewrites paths).
- Landscape `StepImage` was full-bleed `cover` (100%×100%) with header/caption overlaid — the photo dominated and instructions fought it. Portrait displayed up to 900×446 but transferred full-res + blurred full-frame backdrop (double raster).
- No SAM overlay in the composition (only Ken Burns zoom + FOCUS pill); design tokens duplicated (`ProcedureVideo.tsx` literals vs `styles.css` vars vs PIL fallback literals).

### 3. Guide/video inconsistency
- Same step content (shared `job.steps` source) but separate styling: guide via web CSS, video via hardcoded dark-broadcast literals; no shared token file. Guide images `max-width:100%` unbounded; no centered capped card language.

## B. Changes implemented

**Backend deletion (`app/main.py`):**
- `_require_tutorial_manager` (reviewer/admin/expert or owner-creator; 403 otherwise) enforced on delete/archive/unarchive/impact.
- `GET /api/tutorial/{jid}/deletion-impact` — counts (snapshots/revisions/videos/visuals/events/tutorial-evidence) + draft linkage + preservation guarantees.
- `_cleanup_tutorial_records` — deletes snapshots, revisions, video guides, visual assets, processing events, tutorial evidence rows + evidence files (records `evidence_file_errors`); preserves `Procedure/ProcedureVersion` (approved knowledge immutable), `JobSession/JobEvent` (execution history), appends `AuditLog`.
- `DELETE /api/tutorial/{jid}` — impact → cleanup → `tutorials/{jid}` rmtree → audit → transactional commit; idempotent repeat yields 403/404, never partial inconsistency (500 preserves record on DB failure); `storage_warning` surfaced honestly.
- `POST /archive|/unarchive` — role-gated, idempotent `already` on repeat archive, audit-logged.
- `DELETE /api/capture-sessions/{cid}` — reviewer/owner only; 409 when an approved version references the session.

**Frontend deletion:**
- `TutorialLibrary.tsx` — role-gated Remove (archive) / Delete… (impact dialog with counts, preservation note, irreversible warning) / Restore; Archived tab with `include_archived`; refresh + counters; errors preserve the item.
- `TutorialStudio.tsx` — reviewer-only Danger Zone (Remove / Delete permanently with impact panel).

**Video composition (`video/src/` + `backend/app/videoguide.py`):**
- `designTokens.ts` — single source (canvas 1280×720, accent `#ffb020`, radii, safe margins, image card max 780×430, caption rules) mirroring `styles.css`; `ProcedureVideo.tsx` consumes tokens.
- Landscape `StepImage`: full-bleed `cover` → centered contained card (`contain`, max 780×430, radius 18, subtle zoom) on `BRAND_BG`; portrait unchanged (backdrop + contain).
- `_render_sized` (max 1280px copy under `tutorials/{jid}/render/`) applied in `build_video_props`; originals preserved.
- Detail-beat FOCUS pill now names the involved component (looked up from canonical `job.steps`/`job.objects`).
- `validate_video_props` (canvas 1280×720, every scene has in-bounds visual, readable captions ≤500 chars, positive durations) blocks bad renders with logged issues.

**Guide consistency (`frontend/src/styles.css`):**
- `.guide-illustrations img, .card img[src*="illustrations/"]` — capped `min(100%,640px)`, centered, radius + border; images support instructions without pushing them out.

## C. Reviewer deletion workflow
- Library rows (reviewer/admin/expert): Open / Remove (archived, reversible) / Delete… (impact dialog → Delete permanently). Archived tab lists removed items with Restore.
- Studio Danger Zone: same actions in context.
- Backend: 403 on unauthorized; archive only from done/error; unarchive restores done/error heuristic; permanent delete cleans tutorial rows/files, keeps procedures + job history, audits every mutation.
- Active library (`GET /api/tutorial` default) never shows archived/deleted; refresh/navigation cannot resurrect them (server filter, not frontend hiding).

## D. New composition system
- Canvas 1280×720, 30fps, title lead 1.5s (unchanged).
- Safe area x=64, top=160, bottom=170; image card ≤780×430 (~60% width), `contain`, radius 18; captions bottom-52 centered pill (32/38px, ≤2 lines via 220/500-char caps, timed to spoken window); header badge 72px + progress rail; verify panel for expected/tools.
- Highlights: overlay PNGs (SAM-baked) preferred in scene candidates; FOCUS pill labels the component; masks stay aligned via contained (not cropped) rendering.
- Captions follow narration windows (`pick_timed` max-overlap); scene duration = audio + 0.4s tail; no clipping (voiceover spans scenes after title).

## E. Testing results
```
backend: 190 passed, 1 skipped (33s)
  new: test_reviewer_deletion.py (4), test_video_composition.py (7)
  updated: TutorialLibrary.test (impact dialog), guide/tutorial inject (verified-only from prior session)
frontend: 20 files, 117 passed; tsc clean; vite build clean
video: asset-server 5 passed; tsc --noEmit clean
```
- Real render suite (Remotion MP4) covered in repo CI path; this session verified composition via unit validation + sized-copy tests, not a full-length judged render.
- No live Meta calls in tests (mocked); simulated vs live preserved.

## F. Manual verification
**Reviewer deletion:** Library as reviewer → Remove → item leaves All/Ready, appears under Archived → refresh (stays) → Restore → returns. Delete… → impact counts → Delete permanently → disappears everywhere incl. refresh; procedures + Activity history intact; repeat delete → 404/403, no inconsistency. As technician on others' tutorial → 403, buttons hidden.
**Video/guide:** Process tutorial → Guide shows capped centered illustrations → generate video → preview: image card (not full-bleed), readable header/captions, FOCUS pill names part → download matches preview → same step order/titles/objects as guide. Portrait/landscape/square/long-text/silent steps adapt without overflow (validation blocks violations).
