# Guide generation audit — tutorial pipeline, formats, images, versions

Date: 2026-10-29. Branch: `guide-formats-muse-image`. Baseline: 40 backend tests pass, clean tree.

## 1. Current pipeline (`backend/app/tutorial.py::run_job`, background thread)

| Stage | Code | Persists to | Failure behavior |
|---|---|---|---|
| probe | `probe_video` | `TutorialJob.duration_sec/width/height` + `ProcessingEvent(probe)` | `RuntimeError` → job `error` |
| transcribe | `ai.transcribe_timed` | `full_transcript`, `timed_segments` + event | raise on error/empty → job `error` |
| understand | `ai.understand_tutorial` | `objects[{label,first_mentioned_at,obj_id}]`, `steps[{step_number,title,start,end,summary,objects_used}]` + event | never raises (simulated fallback); empty objects → skip segmentation |
| segment (per object) | `_segment_object`, prompt ladder (max 3) + 1 hi-res retry, `_best_track` | `objects[]` incrementally + per-object `segment` events (attempts, confidence, coverage, best frame/box) | graceful: `simulated`→error, no-match→`needs_tap`, low-conf/ambiguous→`needs_tap` |
| illustrate | `make_illustrations` (PIL only) | `data/tutorials/{id}/obj-N{-overlay,}.png`, `diag-obj-N.jpg` on miss | exceptions in hirez/diagnostic swallowed (silent) |
| guide | `ai.generate_guide` → fallback → `inject_illustrations` | `guide_markdown`, `GuideSnapshot(trigger=initial)` + event | never raises; always produces something |
| draft | `_ensure_review_draft` (idempotent on `draft_version_id`) | `Procedure` + `ProcedureVersion(v1,draft)` + steps + `Evidence(image)` rows + audit | failure recorded, job stays `done` |

Endpoints: `start`, `GET /api/tutorial` (shared library, search/status/pagination), detail, `video`/`illustrations` (token-gated), `tap`, `retry`, `DELETE`, `refresh-guide` (deterministic re-inject only), `snapshots[/{id}]`, `diagnostics[/frame]`, `draft` (idempotent create-or-return), `archive/unarchive`, `bundle.zip`.

## 2. Formats today: exactly one

Single Markdown string (`guide_markdown`) with `illustrations/*.png` links + `materials[]`. No format parameter, no selector, no template switch anywhere (`ai.generate_guide`, refresh, snapshots, bundle). System prompt hardcodes `# title / What you need / Steps ###+time / Tips`.

## 3. Version model

`Procedure 1—N ProcedureVersion(status ∈ draft|pending_review|approved|rejected|superseded)`. Approve flips other approved → `superseded`; approved immutable; `new-revision` clones. Tutorial auto-draft = v1 draft, `POST .../draft` idempotent backfill. **No regenerate/change-format path**: retry refuses when done; refresh-guide never calls the LLM or touches the draft.

## 4. Images today: segmentation only, zero generative

`make_illustrations` = PIL crop + polygon/box overlay. `ai.py` image surface = `segment_image`, `suggest_segment_prompts`, `segment_video_clip` (all SAM-3.1) — no `muse-image`, image-gen, annotate, or edit capability anywhere. Illustrations served token-gated; evidence images via `/api/evidence/{id}/image`.

## 5. Provenance: present and missing

Present: `steps[].objects_used`, object attempts/best/track, `ProcedureStep.evidence_refs/visual_refs=[Evidence.id]`, `Evidence{storage_key, source_reference=tutorial:{id}, extra:{tutorial_id,obj_id}}`, `source_evidence.tutorial_id`, snapshot hashes/object statuses, per-stage events.
Missing: step timestamps/frames (dropped at draft creation); `evidence_refs` and `visual_refs` always identical; only overlay (not cutout) gets an Evidence row; no markdown→Evidence/snapshot backlink.

## 6. Cost/rate-limit/retry/timeout

No cost accounting, no rate limiter, no backoff, no 429 branch. Fixed httpx timeouts (90–300s), ffmpeg timeouts, prompt ladder (≤3) + one hi-res retry, provider-failure → labelled `simulated` fallback. Implicit controls: 512px tracking (960px single retry), `objects[:8]`, segments truncated, hash-cache dedupe by `(video_hash, actor, done)`.

## 7. Verified Muse Image API (dev.meta.ai/docs/image-generation, current)

- Model `muse-image-1.0` via Responses API (`POST https://api.meta.ai/v1/responses`): `input` interleaved `input_text`/`input_image` (`image_url` data-URL or `file_id`), multi-turn via `previous_response_id`, result in `image_generation_call.result` (base64) with handle `id`.
- Single-shot: `POST /v1/images/generations` (text→image), `POST /v1/images/edits` with `images: [{image_url|file_id}]` (raw JSON; OpenAI SDK uses multipart).
- Tool control: `image_generation` tool only; web/image search **built-in and on by default** — we will send `tool_enablement: {enable_image_search:false, enable_web_search:false, enable_shell:false}` per the privacy requirement.
- `output_format: png`, `size: "WxH"` (aspect hint), `reasoning_strength: low` (faster, same price).
- Response: `{data:[{b64_json}], output_format, usage{input/output/total_tokens}}`. Flat **$0.01 per image** (not per token).
- Errors: `400` validation/safety (`content_policy_violation`), `503` retryable (retry with backoff), `500` other.
- Repo pattern to follow: raw `httpx` calls with Bearer `META_API_KEY`, `simulated` labelled fallbacks, no key in frontend.

## 8. Pre-existing defects (from audit agents, verified in code)

1. `refresh-guide` rewrites guide+snapshots but leaves the Review draft stale.
2. Tap correction never touches guide/snapshot/draft until manual refresh.
3. `retry` refuses when done; no regenerate path.
4. `evidence_refs == visual_refs` always; only overlay linked, cutout dropped.
5. Steps lose timestamps/frames at draft creation.
6. Silent swallows in `_hirez_retry` / `_diagnostic_frame`.
7. Tap auto-approves (`needs_tap`+illustration → `ok`), no reviewer gate.
8. `inject_illustrations` only matches `### N` / `##` headings.
9. Frontend: dead `{o.illustration && null}` branch; snapshots/pipeline never auto-load; tutorial "Show more" unreachable; narrow Markdown renderer; tap hits video controls; detached-URL downloads.
10. `video_url` has no token (callers append `?token=` out-of-band).

## 9. Implementation plan (phases)

1. **Content model**: `guide_format`/`format_source`/`format_rationale` on snapshot + tutorial; format-aware Spark prompts; deterministic rule-based recommender; format selector UI.
2. **Versions**: generate-new-version → new snapshot; editable draft synced in place, approved → new revision via existing flow; snapshot viewer + compare.
3. **Muse Image adapter** (`ai.image_edit/generate/refine`): raw httpx, tools disabled, timeouts + 1 bounded 503 retry, honest errors (no fake bytes), usage logged.
4. **VisualAsset model** (kind/parent/storage/provenance/status) + endpoints (improve/annotate/alternative/accept/reject), deterministic SVG annotation path, dimension validation.
5. **Frontend**: `GuideFormatSelector`, format renderers, TechnicalImageViewer + panels, provenance display, offline-honest states, responsive checks.
6. **Tests**: backend (formats, recommendation, versions, adapter mocked, provenance, idempotency, authz, validation), frontend (new harness if absent — decide below), live smoke if key present, E2E scenarios A–H.

## 10. Risks

- Muse Image output fidelity (mitigated: never authoritative, reviewer-gated, provenance-labelled).
- Cost: bounded by single-image calls, no auto-variants, `reasoning_strength: low`.
- Scope: this is the largest build on this repo; format renderers reuse one Markdown pipeline to avoid three drifting documents.

Baseline: backend 40 passed; frontend `tsc -b` + `npm run build` green (verified this session before changes).
