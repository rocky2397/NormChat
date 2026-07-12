# Project conventions

- Stack: FastAPI (Python 3.11) backend in `backend/`, React 18 + Vite
  frontend in `frontend/` (also packaged with Electron).
- Backend layout: `routers/` (API endpoints), `services/` (business
  logic), `models/` (Pydantic/DB models), `db/` (persistence).
- Frontend lint: `cd frontend && npm ci && npm run lint` — must pass
  before opening a PR that touches `frontend/`.
- Backend checks: there is no test suite yet. For backend changes,
  verify the app still imports (`python -m compileall backend`) and add
  pytest tests under `backend/tests/` for any new or changed logic —
  new endpoints need at least one test.
- Branch naming: claude/<issue-number>-<slug>
- Never modify: `.github/workflows/`, `.claude/`, anything touching
  OpenAI API key handling (`backend/config.py` env loading), or DB
  schema/migration code.
- The app's core promise is citation accuracy: answers must point to
  the exact source passage in the uploaded PDF. Never change retrieval,
  chunking, or citation logic as a side effect of an unrelated ticket.
