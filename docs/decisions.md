# Decisions

1. **SQLite prototype over PostgreSQL+Supabase** — spec §3 allows SQLite for a single-machine prototype; `DATABASE_URL` keeps PostgreSQL open. Avoids running two backends.
2. **Hand-rolled CSS design system instead of Tailwind/shadcn** — fewer build dependencies for a hackathon slice; same visual/UX requirements (large targets, one accent, accessible focus). Revisit if the design system grows.
3. **Adapters return labelled simulated results without `META_API_KEY`** — the full loop stays demoable and testable; `simulated` is stored and rendered so nobody mistakes it for a live model result. Live request/response schemas must be re-verified against current official Meta docs before enabling (see ai.py comments).
4. **Header-based demo identity** — fastest role demo (technician/expert/reviewer); explicitly not production auth.
5. **Lexical manual search, no embeddings** — per spec §6.2; deterministic, offline-friendly ranking by term frequency with source snippets.
6. **Jobs pin the approved version ID** — later approvals supersede for future jobs only; active/offline jobs never change underneath a technician.
