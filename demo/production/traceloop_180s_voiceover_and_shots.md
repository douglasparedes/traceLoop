# TraceLoop 180s — Voiceover windows and shot list

> Reconstructed from the mission brief: the referenced package files were not
> present in the workspace. Windows below match `traceloop_180s_timeline.json`
> exactly (frame-accurate at 30 fps). No narration is baked into the current
> export (`voiceoverSrc: null`). Record one file per window (or a single file —
> scenes are frame-locked) and set `voiceoverSrc` to mount it without changing
> timing. Suggested levels: voice 0 dB over silent film.

| Window | Frames | Time | Words | Script |
|---|---|---|---|---|
| VO-1 | 0–300 | 00:00–00:10 | ~28 | "What happens when the only person who knows how to fix something is not there? Expertise is hard to transfer, and when it leaves, work stops." |
| VO-2 | 300–1050 | 00:10–00:35 | ~50 | "With TraceLoop, an expert simply records the task and explains what they are doing. This is the adjustment knob. First, check the position, then turn the knob until the indicator lines up." |
| VO-3 | 1050–1740 | 00:35–00:58 | ~55 | "Meta AI goes to work. Muse Spark structures the recording into steps, and every stage carries provenance: live means a real Meta inference call, simulated means a labelled deterministic fallback." |
| VO-4 | 1740–2460 | 00:58–01:22 | ~45 | "Where the picture is ambiguous, the expert corrects it before it ever becomes an instruction. One save, and the guide, the evidence, and the review draft update together." |
| VO-5 | 2460–3060 | 01:22–01:42 | ~40 | "The recording becomes a clear illustrated work instruction, versioned and immutable. Nothing here is a mockup: every screen is the real application." |
| VO-6 | 3060–3660 | 01:42–02:02 | ~40 | "Then a human reviewer checks the draft against its evidence and approves it. That approved revision can never be silently edited, only superseded." |
| VO-7 | 3660–4560 | 02:02–02:32 | ~55 | "Out in the field, another technician opens that approved procedure with no signal. Each step works offline. Completions, photos, and one field issue queue on the device, and sync with the server the moment the connection returns." |
| VO-8a | 4560–4770 | 02:32–02:39 | ~25 | "Here is the loop that matters. The knob label is not visible from this angle." |
| VO-8b | 4770–4950 | 02:39–02:45 | ~25 | "That observation returns to the expert. TraceLoop drafts the fix, quoting the technician, marked low confidence." |
| VO-8c | 4950–5150 | 02:45–02:52 | ~25 | "The reviewer approves the new revision, while the finished job stays pinned to the version it actually ran." |
| VO-9 | 5150–5400 | 02:52–03:00 | ~22 | "TraceLoop: evidence-linked knowledge, approved by humans, built for the field. Knowledge that never gets lost." |

Total ≈ 410 words incl. pauses. Leave ~0.5 s handles at each window edge.

## Shot list (all genuine browser captures; scene cards are the only graphics)

1. Opening card (graphics).
2. Tutorials: recorder idle → upload form filled → "Upload & generate guide" → "Building your guide… 2%" → "Open in Tutorial Studio".
3. Studio Overview: source recording player, task description, per-stage AI processing (Source ingestion COMPLETED / Transcription PENDING / Task understanding COMPLETED+Simulated muse-spark-1.3 / Segmentation SKIPPED / Procedure generation COMPLETED+Simulated / Review draft COMPLETED).
4. Studio Content: corrected steps (Locate the adjustment knob / Check and align the indicator), "Canonical steps saved" toast.
5. Studio Guide: Illustrated Work Instruction format, "Generate new version", immutable version history with "simulated model" badges, regenerated corrected guide.
6. Review: draft with corrected steps → Submit for review → role Reviewer → Approve → "Yes, approve" → APPROVED badge → Procedures library (APPROVED REV, OFFLINE CACHED).
7. Mobile 390×844 (pillarboxed, uncropped): Procedures card APPROVED → "Saved for offline use" toast → Start job → airplane ON ("Offline · local") → step completion → photo queued → field note saved → finish → reconnect → Activity "Synchronization complete", 0 pending, server timestamp.
8. Activity: finished job event history + photo → feedback (Step 2 confusing + "Knob label is not visible from this angle.") → Submit → Create improvement proposal (confirm dialog) → v5 draft with before/after + "simulated analysis (no Meta key)" → submit → approve → v5 APPROVED; job stays pinned to v3 (API-verified).
9. Closing card (graphics): repo URL, Built with Meta AI.

## Provenance labels visible in footage

"Simulated" stage badges, "simulated model" snapshot tags, "no META_API_KEY" verification notes, "simulated analysis (no Meta key)" proposal banner. No live Meta inference occurred (no key in this environment); nothing is presented as live.
