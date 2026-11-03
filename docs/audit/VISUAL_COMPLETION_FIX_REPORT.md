# TraceLoop — Visual Segmentation + Job Completion: Root Causes, Fixes, Validation

**HEAD:** `312fe50` (+ working-tree stabilization in this session)
**Date:** 2026-11-03

## 1. Root causes found

### A. Objects not reliably segmented (`chocolate pieces` case)

1. **Transcript-only discovery in narrated path.** `run_job` branched exclusively: `narrated → understand_tutorial(transcript)` OR `visual_first → analyze_tutorial_frames`. A narrated tutorial never ran visual analysis, so visible-but-unmentioned objects never entered the inventory.
2. **Hard cap `objects[:8]`** (`ai.py:965`) with no reporting. Task-relevant objects beyond 8 were silently dropped. Visual per-step cap `objects[:8]` (`ai.py:1374`) compounded it.
3. **Weak SAM prompts.** `prompt_variants` ladder dropped adjectives to head noun only, ignoring synonyms/context. No `alternative_names`/`properties` captured.
4. **Unvalidated visuals published (partially).** `inject_illustrations` published any `needs_tap` non-ambiguous overlay as guide evidence; frontend Guide tab filtered only `!!overlay`. Low-confidence crops could appear as successful illustrations.
5. **No Muse Image fallback.** Missing step visuals had no generative path; `image_generate` existed only in VisualStudio manual flow.
6. **Frontend messages accurate but unhelpful in isolation.** `App.tsx:1342` “Highlighting unavailable…” is the capture-review SegmentOverlay path (no segmentation geometry). Tutorial equivalents showed diagnostic frames without distinguishing verified vs diagnostic vs AI states clearly enough.

### B. Completed jobs reappear as available

1. **Library availability ignored executions.** `Library` (`App.tsx:851`) filtered only on `approved_version_id`/draft/review; never read `jobs: JobRow[]`. `ProcedureDetail.canStart` only checked `version.status==="approved"`.
2. **`GET /api/jobs` lacked execution context.** Returned `procedure_title` but no `procedure_id`/`procedure_version_id`, so the frontend could not join completions to procedures.
3. **`POST /api/jobs` allows repeat runs by design** (correct for reusable procedures) — but the UI showed `Start Job` identically for never-run vs completed, so a finished execution looked like a pending available job. No `Completed · date · runs` badge, no `Run again` vs `Start job` distinction, no `View last execution`.
4. Completion itself persisted correctly (`status=finished/outcome/ended_at` via `_finalize_job_core`); the bug was display/scoping, not persistence.

## 2. Changes implemented

**Backend `app/ai.py`:**
- `MAX_OBJECTS` (env `TRACELOOP_MAX_OBJECTS`, default 32) replaces `[:8]`; `understand_tutorial` prioritizes by `first_mentioned_at`, returns `dropped[]` transparently; schema requests `alternative_names` + `properties`.
- `_clean_visual_steps` per-step cap 8→16.

**Backend `app/tutorial.py`:**
- `_normalize_label` + `_merge_object_inventories` (exact-normalized dedup, stable ids, `discovery_source` transcript/visual/both, union synonyms/timestamps/evidence, no merging of distinct instances).
- `run_job`: narrated path adds bounded (≤8 frames) visual supplement via `analyze_tutorial_frames` and merges; visual_first path with transcript adds transcript supplement and merges. Failures logged as `skipped`, never fatal.
- `prompt_variants(label, synonyms)` — canonical → synonyms → simplification ladder, `MAX_PROMPT_ATTEMPTS=3`.
- `_segment_object` passes synonyms.
- `inject_illustrations` — only `status==="ok"` publishes; needs_tap/error/ambiguous stay reviewable.
- `ensure_ai_step_illustrations` (max 5, live only) + `inject_ai_illustrations` — Muse Image explanatory aids labelled `AI-generated … not a photo … verify against real equipment`; failures recorded with provenance, never fake success.
- Guide `proc.safe_record` summaries now include `ai_illustrations`, `dropped`, supplement notes.

**Backend `app/main.py`:**
- `GET /api/jobs` adds `procedure_id`, `procedure_version_id` (additive, no migration).
- Diagnostics already return full `objects` (attempts/track/coverage/margin/prompts/simulated) + events; no secrets present (verified — no keys in payloads).

**Frontend:**
- `TutorialMode.tsx`: `TutObject` gains `alternative_names/properties/discovery_source/simulated/ambiguous_match`; guide filter requires `status==="ok" && overlay`; Objects tab shows `segmented · verified` vs statuses, `found via`, synonyms/traits, simulated tag, diagnostic labelled “not a segmentation result”, manual-review badge.
- `App.tsx`: `JobRow` gains procedure/technician ids; `Library` receives `jobs` + `goHistory`, computes per-procedure `related/finished/open/lastDone`, shows `In progress` / `Completed · date · N runs` badges, primary `Start job` → `Run again` / `Start additional run`, plus `View last execution`; `ProcedureDetail` same with execution-history panel distinguishing open vs completed and stating new runs never reopen finished ones.

## 3. Database and API changes

- No migrations. `TutorialJob.objects/steps` JSON gains optional keys (`alternative_names`, `properties`, `discovery_source`, `evidence_frames`, `ai_illustration` provenance) — backward compatible.
- `GET /api/jobs` response adds `procedure_id`, `procedure_version_id` (frontend old code ignores unknown fields; new code requires them).
- No endpoint removed; `/finish`↔`/finalize` unified core from prior stabilization untouched.
- Sync: no change (completion flow already idempotent).

## 4. Tests and validation

```
backend: 179 passed, 1 skipped (70s, incl. 2 real Remotion renders)
  new: tests/test_visual_discovery.py (11 passed), tests/test_job_completion.py (4 passed)
  updated: test_guide_illustrations (verified-only), test_tutorial inject (ok-only + missing-status),
           test_guides muse-image counter reset (pipeline supplement isolated)
frontend: 20 files, 117 passed (incl. new ProcedureCompletion.test.tsx: 2 passed)
  tsc -b clean, vite build clean
```

- Live Meta API **not** exercised (no `META_API_KEY` in test env); live paths verified via mocks. Simulated vs real distinguished via `simulated` flags and `Live/Simulated` tags — mocks never claimed as live.
- `test_no_segmented_without_valid_evidence`, `test_sam_empty_frames_stay_needs_tap`, `test_inject_only_publishes_verified_ok` guard the “no fake segmentation” invariant.
- Diagnostics manually inspected: `GET /diagnostics` returns attempts/prompts/coverage/margin/best_* /quality/simulated per object; no `META_API_KEY`/tokens present.

## 5. Remaining limitations

- Visual supplement doubles Meta calls on narrated tutorials (≤8 frames + transcript). Bounded but not free; reduce `sample_keyframes` max or gate behind duration if cost becomes an issue.
- Muse Image fallback max 5 steps/tutorial, generic line-art only; safety-sensitive steps still show real frame + request review (no auto-generation for ambiguous safety content beyond generic aid + verify caption).
- SAM validation checks confidence/margin/distinct/coverage/bbox, not pixel-level mask geometry beyond `_mask_svg` parse success; empty-mask edge is caught via `no_match`/needs_tap but a degenerate non-empty polygon could still score — monitor `quality.issues`.
- Playwright E2E for record→segment→approve→execute→complete still out of scope; vitest + pytest cover lifecycle.
- TWA assetlinks placeholder, Coolify volume mounts, Meta model IDs still require pre-submission verification (see prior stabilization report).

## 6. Manual verification

**Visual AI:**
1. Record/upload a video with ≥3 task objects; mention some, leave ≥1 relevant object unmentioned.
2. Process; open Guide → steps show verified overlays only for `ok` objects.
3. Objects tab: check `found via transcript/visual/both`, synonyms, attempts (`prompt → frames`), coverage/margin, `simulated` tag when offline, `manual review required` for needs_tap.
4. Steps lacking verified visuals (live key configured) show `AI-generated explanatory illustration (not a photo…)` with verify caption; offline shows diagnostic frame labelled as diagnostic.
5. `Download diagnostics (.json)`: confirm per-object `attempts`, `best_*`, `coverage`, `distinct_count`, `margin`, `simulated`, `note`; explain any `chocolate pieces` miss directly from `note` + `attempts`.

**Job completion:**
1. Procedures → open approved procedure (no badge) → Start job → complete → Finish.
2. Return to Procedures: card shows `Completed · <date>` + `Run again` + `View last execution`; primary is no longer bare `Start job`.
3. Open detail: execution-history panel shows completed timestamp + “never reopens the finished one”.
4. Refresh + sign in again: state persists (server `GET /api/jobs` shows `finished`).
5. Start `Run again`: new active job created, original stays `finished`; tech-2 unaffected.
6. Offline: finish offline → pending-sync completion shown, never reverts to available; sync → server confirms.
