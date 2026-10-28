# Demo runbook (spec §17 scenario)

Prep: start backend + frontend, open http://localhost:5173, Settings → Seed demo procedure.

1. **Capture:** Capture tab → Create session → Record (or keep the prefilled narration) → Save corrected transcript → Attach photo → Generate draft. Labelled simulated unless a real `META_API_KEY` is configured — say so on stage.
2. **Highlight:** In Capture, run "Highlight blue adjustment knob", confirm/reject the overlay.
3. **Review:** Top-bar role → Reviewer. Review tab → open the draft → Submit for review → Approve. Show that editing the approved version is refused and "Propose new revision" forks a draft.
4. **Execute:** Role → Technician. Procedures → Save for offline use → Start guided job.
5. **Go offline:** Enable airplane mode / DevTools offline. Complete 2 steps, record an issue ("Tool unavailable"), reload the page — progress and the pending-sync counter survive.
6. **Sync:** Reconnect → Sync now → History shows the finished job and event counts. Re-syncing creates no duplicates (unique event IDs).
7. **Fallback:** If any live Meta call fails on stage, the labelled simulated path demonstrates the identical workflow; never present it as a live result.
