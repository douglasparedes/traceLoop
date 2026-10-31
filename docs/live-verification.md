# Live provider verification checklist

Automated mocks prove our code paths; only a keyed run proves the provider
contracts. Run `backend/scripts/live_smoke.py --live` with `META_API_KEY`
set (env var or gitignored `backend/.env`), then tick each box with the
observed output. Do NOT commit keys or paste them into chat — paste the
script's printed summary only.

## Preconditions

- [ ] `META_API_KEY` present locally only (`backend/.env`, never committed)
- [ ] Network access to `https://api.meta.ai`

## Contract checks (script asserts shapes automatically)

- [ ] `transcribe.shape` — `segments` is a list, `simulated` key present, model reported
- [ ] `understand.shape` — `objects`/`steps` lists; first object has label/first_mentioned_at/obj_id
- [ ] `segment.shape` — status in ok/no_match/error with a frames list and note
- [ ] `image_edit.bytes` — base64 decodes to non-empty bytes, model + usage recorded (or honest error status)
- [ ] `image_generate.bytes` — same as above for text-to-image

## Human review of output (paste observations)

- [ ] Transcription of the tone clip is empty or marked uncertain (a tone is not speech — any confident fake transcript is a finding)
- [ ] Understanding extracts the screwdriver object with a sane timestamp
- [ ] Segmentation note matches reality (ok with boxes, or honest no_match)
- [ ] Image edit preserves the red square (spot-check the bytes visually if saved)
- [ ] Usage metadata present (proves billing visibility)

## After the run

- Record the date, model IDs observed, and any contract drift in this file.
- If a contract changed (new required field, renamed endpoint), update the
  adapter AND the mocked tests to the new contract — mocks must mirror reality.
- Delete the key from the local shell history if exported inline (`$env:META_API_KEY`
  in-process only is safest; prefer `backend/.env`).

## Log

| date | models observed | result | notes |
|---|---|---|---|
| _pending_ | — | — | — |
