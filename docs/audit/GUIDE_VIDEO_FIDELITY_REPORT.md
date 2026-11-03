# TraceLoop — Guide-to-Video Source of Truth, Caption Dedup & Balanced Composition

**HEAD:** `171eeea` + working-tree implementation (this session)
**Date:** 2026-11-04

## 1. Root causes

1. **Video planned from live job, not the frozen guide.** `run_video_guide_job` passed live `job.steps/objects/guide_markdown` into `ai.plan_video_scenes`, which regenerated titles/narration/captions steered by (not copied from) the guide. `GuideSnapshot` stored markdown but never steps, so the "exact snapshot" could not be reconstructed. Result: reordered/reworded steps, invented lines, transcript-vs-guide divergence.
2. **Caption duplication by construction.** `plan_visual_beats` picked transcript overlap per beat window *plus* fallbacks (recap/caption/expected/tools), while `BeatView` rendered header title + pill + full `CaptionBar(beat.body || scene.caption)` on every beat. The same sentence appeared as static text and subtitle simultaneously, and chunks repeated across beats.
3. **Illustrations dominated.** Landscape rendered full-bleed `cover` (100%×100%); portrait up to 900×446 centered. Sources saved at native resolution and served as-is. No supporting-card constraint.
4. **Edited plans dropped linkage.** `validate_scene_plan` stripped `objects_used/narration/caption_chunks`, degrading accepted/overlay matching to keyframes. Duplicate `_latest_guide_snapshot` definitions; duplicated `_segments_for_range`.
5. **No fidelity gate.** Nothing verified step count/order/ids, warnings, or visual refs before render.

## 2. Architecture changes (guide = source of truth)

- **Models:** `GuideSnapshot.steps` (ordered canonical steps, backfilled for old snapshots); `VideoGuide.source_snapshot_id/source_steps_hash/source_content_revision` + lightweight `ALTER TABLE` migrations in `main.py`.
- **`snapshot_guide`** now persists steps alongside markdown/object statuses.
- **Deterministic planning:** new `_scenes_from_guide_steps` — exactly one scene per guide step, in order, no AI reinterpretation. Narration = guide wording; `caption_chunks` = ≤90-char phrase splits; `instruction` = ≤140-char concise panel text; `objects_used/expected/tools` carried through. Fidelity guard raises on count/order mismatch.
- **Automatic path** (`run_video_guide_job`) loads the latest snapshot, uses its steps (fallback: live steps for pre-change snapshots), records source ids/hash/revision on the `VideoGuide` row and provenance. AI `plan_video_scenes` retained only for the explicit Studio suggest endpoint; stored edited plans validated with linkage preserved.
- **Beats rewritten:** one caption chunk per beat, sequential, exactly once; frame shares proportional to chunk length (1s floor); verify beat only shows expected/tools. No transcript re-pick, no fallback repetition.
- **Composition** (`ProcedureVideo.tsx` + `designTokens.ts`): instruction-first side layout — left text panel (~660px/52%), right supporting image card (380×300, ~30%, `contain`, radius 18, object label chip), bottom caption safe area with exactly one chunk, header badge + step indicator, progress rail. Verify beats keep the centered expected-result card.
- **Validation** (`validate_video_props`): canvas 1280×720, per-scene visual + readable dims + sane aspect, no duplicate beat bodies, static instruction never verbatim-equal to a caption chunk, contiguous order, no duplicated steps.

## 3. Content fidelity (guide → video)

| Guide source | Video segment | Result |
|---|---|---|
| Snapshot step_number/title/summary | Scene step/title/narration/caption_chunks | Exact 1:1, order enforced, guard raises on mismatch |
| objects_used per step | objects_used per scene → overlay matching + FOCUS label | Preserved through validation (was dropped) |
| expected/tools | Verify beat + instruction panel | Preserved |
| Visual refs (overlay/cutout/keyframe) | `resolve_scene_visuals` priority (unchanged) | Reused, render-sized copies |
| Newer draft after snapshot | Ignored (snapshot pinned, staleness detectable) | No mixing |

`test_guide_video_fidelity.py` (6 tests): 6 steps → 6 segments in order with ids; transcript mismatch still follows guide; beats cover narration exactly once; static-vs-caption duplication detected; order/dup validation; warnings/tools preserved.

## 4. Visual design

- Canvas 1280×720, 30fps, 1.5s title lead (unchanged).
- Text panel x=64 w=660: badge 56px, title 34px, instruction 26px, expected/tools muted.
- Image card x=764 w=380 h=300 (~30% width), contain, radius 18, label chip for the focused object.
- Caption bar bottom: single chunk, 32px, centered, max ~90 chars/2 lines.
- Transitions: dissolve between beats (8-frame overlap), subtle zoom 1→1.06/1.02→1.1; no generic bounces or random motion.
- Shared tokens (`designTokens.ts` ↔ `styles.css`): accent `#ffb020`, radii, type scale; guide Markdown images capped `min(100%,640px)` centered.

## 5. Captions & narration

- Narration text = guide wording; voiceover audio = recorded cut per step range (unchanged mechanism). Captions = chunked narration slices shown one at a time, timed proportionally to audio duration — never the full paragraph, never repeated across beats, never persisting into the next step.
- Old transcript-window re-pick removed; fallback chains removed. `caption_src: "guide step"` recorded per scene.

## 6. Validation

```
backend: 197 passed, 1 skipped (includes 6 fidelity + updated beats/visuals/composition suites)
frontend: 20 files, 117 passed; tsc clean; vite build clean
video: asset-server 5 passed; tsc --noEmit clean; real Remotion renders pass
```

- Real render verified: synthetic 2-scene props → MP4 (h264, 1280×720, 5.0s) via `_render_video`; frame extracted at t=3s: 1280×720, left text region vs right image-card region vs dark caption bar all distinct — side layout confirmed in pixels, not just components.
- Distinguish: unit/props tests use mocks and synthetic media; Remotion renders use real ffmpeg/testsrc media and the real `render.mjs`; no live Meta calls in this session (simulated flags preserved).

## 7. Manual verification

1. Open a generated guide (≥6 steps) → note snapshot id in diagnostics.
2. Generate Video → row records `source_snapshot_id/steps_hash/content_revision` (check video-guide detail/provenance).
3. Compare scenes to guide: same 6 titles in order, one segment each, warnings/expected intact, no invented steps.
4. Play: each step shows `STEP N/M` + short title + concise instruction (not the full paragraph), supporting card right (~30%), one caption chunk at a time synced to voice; no repeated sentences across header/body/caption.
5. Inspect frames: images contained with aspect preserved, highlights aligned, captions inside bottom safe area, no overlap with the object card.
6. Edit the guide → new snapshot → old video flagged stale via `describe_staleness`; regenerate to update.
7. Preview vs downloaded MP4: same file served (`storage_key`), identical composition.
