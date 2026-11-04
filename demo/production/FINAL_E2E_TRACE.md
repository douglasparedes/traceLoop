# FINAL_E2E_TRACE.md — end-to-end workflow verification (recovery production)

Single isolated case: cookie chain only. Rehearsals, probes, knob cases excluded
(see traceability JSON). Verification method per row: DB query + on-camera take.

| # | Claim in film | Evidence | Take proving it |
|---|---|---|---|
| 1 | Real 90 s kitchen recording is the input | `demostration.mp4` SHA `c61d82f5…`, 89.63 s, 406×720; `-visual` derivative frame-identical (`-c:v copy`) | S1 plays the file; S2 preview shows its frames |
| 2 | Upload is real (progress, dedupe, done) | Upload sessions `cb73f141`, `31d0641f`, `49927693`, `936eeea8` in server log; scratch tutorials `9466522e`, `b8302fd4` (archived) ran live Spark | `dabf8a9e`: typed fields, file, 90%→done button |
| 3 | Visual-first is correct; no speech exists | Audio audit: max −5.5 dB ambient, 88/89 1-s windows < −28 dB; `extract_audio: skipped (has_audio false)`; 0 `transcribe` events for `a15e048d` | S3 shows PENDING transcription, never a transcript |
| 4 | Live Spark understanding | `analyze_frames` event: provider meta, `muse-spark-1.3`, 25,314 ms, 5 obs / 0 steps / 0 objects + `missing_information` + `dropped` (clamping) | S3 stages list; audit §4.4 rules out defect |
| 5 | Live Spark guides (4 snapshots, all `simulated: 0`) | `guide_snapshots` rows: reference_manual + 3 work_instruction + interactive (this session) | S5 version history + honesty note on camera |
| 6 | Segmentation legitimately skipped | `segmentation_results` table empty globally; pipeline bypasses SAM when `objects == []` | S3 SKIPPED badge; no masks anywhere in film |
| 7 | Expert authored the 3 true steps | Content rev 1 (empty Untitled) → rev 2; v2 steps match footage (ingredients/whisk/tray); `start_sec=end_sec=0.0` → film claims no time ranges | `c521b15` act + save banner; r4hold |
| 8 | Video guide is real app output | `video_guides` v1/v2 `error` (honest validator), v3 `ready`, `simulated: False`, canonical-hash provenance; MP4 1280×720 18.2 s inspected (caption cards + keyframes) | `123a7543` tab + `videoguide-v3.mp4` playing |
| 9 | Reviewer submitted + approved (filmed live) | `procedure_versions`: v6 `approved`, `reviewed_by demo-reviewer`, timestamp; queue Pending (1)→(0) on camera | `48c73e98` + REV 6 card (`27ad52ad`) |
| 10 | Job ran pinned revision offline, server confirmed | `7e34ab30` finished, pin `aacb11e0`; 7 events; mobile take shows offline banner + pinned rev + sync-complete + 0 pending | `93dc936` + `0bc424d8` download beat |
| 11 | Feedback is verbatim technician words | `field_feedback` payload: step 2 confusing + "Whisking in the video is brief…" + photo/note events | `99faac1` verdicts + note + submit |
| 12 | Proposal is live Spark quoting the tech | v5 `source_evidence.proposal`: `simulated False`, `muse-spark-1.3`, `job 7e34ab30`, Before/After, medium confidence | `2a9ddad` diff scroll |
| 13 | The fix was approved (history) | v5 was `approved` (reviewed 02:17 UTC) then superseded by v6 approval; v5 steps carry the dry-pockets fix, v6 does not (format regen sources tutorial content) | archival `h8c` REV 5 badge + this table |

Code fix shipped during production: `videoguide._scenes_from_guide_steps` shortens
the static panel when it would duplicate a caption chunk (the silent-tutorial
collision); 28 video tests green; v3 rendered ready after the fix. See audit §4.
