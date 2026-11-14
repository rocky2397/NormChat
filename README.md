# NormChat

RAG-powered chat interface for construction professionals in the DACH region. Upload your own norm PDFs (DIN, LBO, Eurocode, ÖNORM) and query them in natural language with cited source passages and in-PDF highlighting.

## Prerequisites

- Python 3.11+
- Node.js 20+
- OpenAI API key (for embeddings and chat)

## Setup

### Backend environment

The Python venv must live at `~/.venvs/normchat` (not inside the repo —
an in-repo venv breaks on the exFAT drive, and the Electron app looks
for it at this path):

```bash
python3 -m venv ~/.venvs/normchat
source ~/.venvs/normchat/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
# Add your OPENAI_API_KEY to backend/.env
```

### Frontend dependencies

```bash
cd frontend
npm install
```

## Running

### Electron app (default)

From the repo root (or from `frontend/`):

```bash
npm run dev
```

This starts the Vite dev server, launches the Electron app, and starts
the FastAPI backend automatically (from `~/.venvs/normchat`). No
separate backend step is needed.

### Browser (alternative)

Start the backend manually:

```bash
cd backend
source ~/.venvs/normchat/bin/activate
uvicorn main:app --reload --port 8000
```

Then in a second terminal:

```bash
cd frontend
npm run dev:web
```

App: http://127.0.0.1:5173 — API docs: http://127.0.0.1:8000/docs

## Usage

1. Create a project (optionally set a Bundesland).
2. Upload PDF norm documents to the project.
3. Ask questions in the chat panel.
4. Click a source card to open the PDF at the cited page with the passage highlighted.

## Architecture

- **Backend:** FastAPI, SQLite, ChromaDB (per-project), LangChain, OpenAI
- **Frontend:** React (Vite), Tailwind CSS, PDF.js
- **Storage:** Local filesystem under `backend/storage/{project_id}/`

Documents and embeddings are isolated per project. Norm PDFs are never bundled with the application — engineers upload their own legally obtained copies.

## Evaluation

The hard case for norm RAG is not finding *a* plausible passage. It is citing
the **ÖNORM EN clause together with its ÖNORM B national supplement**, which
shares clause numbers and vocabulary with the EN text. An answer that cites
only the EN where a national deviation applies is wrong, however well it reads.

The question set is **7 real questions from a practising Austrian structural
engineer**, not synthetic ones, run against the full Austrian Eurocode corpus
(39 PDFs, EN and B variants; ~10.5k chunks). It is graded in two layers.

### 1. End-to-end answer grading

Each answer gets three checks: a **substantive** national-annex clause is
cited (a cover, foreword or contents page does not count), the cited clause
is the right one, and the PDF highlight lands on the sentence the answer
relied on. Grades are `gut` / `mittel` / `schlecht` (good / partial / fail).
An **unsourced claim is `schlecht`**, worse than an honest gap. All runs were
re-scored when this rule was tightened, so the trend is comparable. Selected
runs:

| run | Q1 | Q2 | Q3 | Q4 | Q5 |
| --- | --- | --- | --- | --- | --- |
| 1 · baseline | gut | mittel | schlecht | schlecht | schlecht |
| 5 · clause lookup | gut | mittel | schlecht | schlecht | **gut** |
| 8 · + compound expansion, part-conflict handling | gut | mittel | schlecht | **mittel** | gut |
| 2026-08-13 · clause ordering (Q3 re-run only) | | | **gut** | | |

Baseline → current: **1 → 3 questions at `gut`, 3 → 0 at `schlecht`**
(counting the Q3 re-run). Q3 needed three stacked fixes, each invisible until
the previous one landed: the B document's register table was winning every
clause lookup, page deduplication was blocking the right clause, and the
clause-lookup limit was one too small. Q2 has been `mittel` in every run. Full
history: [`eval/runs/README.md`](eval/runs/README.md); rubric and gold labels:
[`eval/questions.md`](eval/questions.md).

### 2. Per-stage retrieval probe

A headless probe runs retrieval only, with no answer generation, and reports
where each gold `(norm, page)` label ranks at every pipeline stage. That
separates "never retrieved" from "dropped by the reranker" from "in context
but ignored", which an end-to-end grade cannot.

| stage | recall@10 | recall@100 |
| --- | --- | --- |
| dense | 8/13 (0.62) | 11/13 (0.85) |
| lexical (BM25) | 6/13 (0.46) | 8/13 (0.62) |
| fused | 6/13 (0.46) | **12/13 (0.92)** |
| reranked | 6/13 (0.46) | 6/13 (0.46) |
| + annex-delta admission | 6/13 (0.46) | 8/13 (0.62) |
| final context | 6/13 (0.46) | 9/13 (0.69) |

**What it shows:** the candidate pool is good. Fusion recovers 12 of 13 gold
passages in the top 100. The loss happens at the **reranker cut**, which the
annex-delta admission and clause-lookup stages partly win back. That is where
the next work goes. Run it yourself from `backend/`:

```bash
python -m eval.retrieval_probe --project <project-id>
```

When the pipeline was refactored into named stages, success meant the eval
*not* moving: the probe output and the returned sources for all 7 questions
were byte-identical before and after, and all 179 tests passed with no test
changes.

### Caveats

- **Small set:** 7 questions and 13 gold labels. These are regression signals,
  not benchmark numbers, and `CLAUSE_LOOKUP_LIMIT` is explicitly fitted to them.
- Answer grades were assigned by Claude on a single generation at non-zero
  temperature, and the highlight check was not run for every row.
- The Q3 `gut` comes from a single-question re-run. The full table is due to
  be regenerated in one pass by a human once the question set is confirmed.
- A PDF-extraction defect still corrupts one formula (`V_Rd,max`) on one page.
  It is tracked separately.

## Development order

Built according to `SPEC.md`:

1. Ingestion pipeline
2. Retrieval and chat
3. Project/document UI
4. Chat with source cards
5. PDF viewer with highlights

## Example data

Place local test PDFs in `example_data/` (gitignored). This folder is not committed to the repository.

## Deployment

The app is Dockerized (root `Dockerfile`) for sharing a hosted instance with collaborators. A single container builds the frontend and serves it from FastAPI alongside the API, gated by a shared username/password behind a login page (session cookie, no separate user accounts).

To deploy on Render using the committed `render.yaml` blueprint:

1. Push this repo to GitHub (if not already there).
2. In the Render dashboard: **New > Blueprint**, connect the repo — it will pick up `render.yaml` automatically.
3. Set the required environment variables when prompted (these are marked `sync: false` and are never committed):
   - `OPENAI_API_KEY`
   - `AUTH_USERNAME` / `AUTH_PASSWORD` — the shared login credentials
   - (`SESSION_SECRET` is auto-generated by Render)
4. Deploy. Render gives you a public `https://<service>.onrender.com` URL — that's what you share with your collaborator.

### Persistence and sizing

`render.yaml` provisions a 3 GB persistent disk at `/var/data`. Uploaded PDFs,
the per-project Chroma collections and the SQLite metadata all live there
(`STORAGE_DIR` and `DATABASE_URL` point at the mount), so they survive
redeploys and restarts.

The instance is `standard` rather than `starter`, which is a memory
requirement, not a preference. Measured peak resident memory with one corpus
loaded is ~1.2 GB: torch and chromadb account for 436 MB, loading the
21,909-chunk German corpus adds ~396 MB (retrieval reads the whole collection
per query), and the cross-encoder another ~350 MB. Starter's 512 MB cannot
hold that, and free instances cannot mount a disk at all. Run **one** uvicorn
worker: a second would duplicate all of the above.

Approximate cost at the time of writing: $25/month for the instance plus
$0.25/GB/month for the disk.

### Loading a corpus

Ingestion is synchronous inside the upload request, and the frontend sends a
whole drop as a single request, so dropping 137 PDFs at once will exceed the
proxy timeout. Either upload in batches of 10–20, or seed the disk directly:
copy an already-built `storage/<project-id>/` directory and `normchat.db` onto
the mount. Seeding also avoids re-embedding a corpus you have already indexed
locally.

Each corpus belongs in its own project. Projects have separate Chroma
collections and queries never cross between them, so an Austrian (ÖNORM) and a
German (DIN) project stay independent with no extra configuration.

If `AUTH_USERNAME`/`AUTH_PASSWORD` are left unset, the login gate is disabled entirely (this is intentional, so local dev needs no extra config) — don't deploy without setting them.
