# Processing observability — AI/model timeline, SAM diagnostics, tutorial persistence

## What is logged

Every AI/model stage writes a `ProcessingEvent` row **and** one JSON line to
stdout (Coolify logs), sharing a `correlation_id` per pipeline run:

- tutorial: `probe → transcribe → understand → segment (per object) → guide → draft`
- capture/transcribe/segment/suggest flows and tap corrections (`tap` stage)
- review-draft creation from tutorials

Each event stores: entity, stage, operation, provider, model, status
(`succeeded|ok|failed|error|simulated|no_match|needs_tap|processing`),
duration, and a **summary** (prompts tried, confidences, frame counts,
coverage, margins, transcript/guide sizes, error type/message). Never stored:
API keys, auth headers, full raw provider payloads, duplicated video bytes.

## Reading a SAM miss

1. Open the tutorial → **Pipeline** tab. Find the `segment` event for the
   object: it shows every prompt tried in order (including the hi-res retry),
   frames seen vs. with matches, coverage, distinct-candidate count, margin,
   best frame/time/confidence/box, and a human-readable note.
2. **Objects** tab: missed objects show a diagnostic frame (the exact frame
   SAM was asked about) plus the same numbers, with tap-to-correct.
3. **Download diagnostics (.json)**: transcript, objects with full attempts,
   guide snapshots, and all events — attach it to bug reports.
4. Correlate with server logs via the run's `correlation_id`.

## Guide history

Every generation is snapshotted (`trigger`: initial, refresh, tap, retry)
with model, simulated flag, hash, materials, and per-object statuses. The live
guide never overwrites history; snapshots are viewable per tutorial and
included in the diagnostics bundle.

## Tutorial drafts and persistence

- The tutorial library shows **all** demo-actor tutorials (newest first) with
  search, status filter, and pagination — a tutorial is never hidden by role
  switching or a 20-item cap.
- On `done`, each tutorial auto-creates **one** Review-queue draft (idempotent
  on `draft_version_id`; linked evidence = SAM illustrations). Older tutorials
  get theirs via **Send to Review as draft** (same endpoint retries failures).
- If the linked draft is still editable, later corrections update it; never
  silently once it leaves `draft`.
- Archiving hides finished tutorials from the default list; hard delete stays
  an explicit, confirmed action.
- Ops check (`docs/deployment-coolify.md`): `/data` and `/app/backend/data`
  must be persistent volumes, or tutorials, media, snapshots, and evidence
  files die on redeploy (rows without files).
