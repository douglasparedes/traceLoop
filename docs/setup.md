# Setup

Prerequisites: Python 3.11+, Node 18+.

1. Backend: `cd backend && python -m venv .venv && .venv\Scripts\Activate.ps1 && pip install -r requirements.txt && uvicorn app.main:app --port 8000`
2. Frontend: `cd frontend && npm install && npm run dev` → open http://localhost:5173
3. Optional live AI: set `META_API_KEY` (backend env only; see [.env.example](../.env.example)). Without it, AI features run in labelled simulated mode.
4. Tests: `cd backend && python -m pytest tests -q`

Deployment note: single-machine prototype on SQLite. For shared hosting, set `DATABASE_URL` to PostgreSQL, add real authentication, object storage, and HTTPS; do not expose the demo header-auth build publicly.
