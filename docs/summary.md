# Summary

**Problem.** Expert maintenance knowledge leaves with the expert. Technicians in low-connectivity settings get static manuals, no guided execution, and no structured way to feed field observations back.

**Users.** Experts (capture), reviewers (approve), technicians (execute offline).

**Approach.** TraceLoop turns narration + photos + manual excerpts into a schema-validated draft with evidence refs and explicit uncertainties. FieldGuard executes only human-approved immutable versions, queues every completion/issue event in IndexedDB, and syncs idempotently. Observations can seed a new draft revision; approved versions never change.

**Implemented (evidence: backend tests + code).** Capture sessions with transcript correction; PDF manual indexing + lexical search with source locations; draft generation (simulated without a key); review/approve/reject with role checks; approved-version immutability (HTTP 409); guided job with complete/blocked/skip/issue; durable offline queue; idempotent `/api/sync/events`; SAM-style bbox overlay with confirm/reject (simulated without a key); audit log; seeded demo.

**Not yet verified.** Live Meta API calls (no key in this environment), production auth, object storage. See [review.md](review.md).
