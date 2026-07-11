# NormChat

RAG-powered chat interface for construction professionals in the DACH region. Upload your own norm PDFs (DIN, LBO, Eurocode, ÖNORM) and query them in natural language with cited source passages and in-PDF highlighting.

## Prerequisites

- Python 3.11+
- Node.js 20+
- OpenAI API key (for embeddings and chat)

## Setup

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add your OPENAI_API_KEY to .env
uvicorn main:app --reload --port 8000
```

API docs: http://127.0.0.1:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://127.0.0.1:5173

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

## Development order

Built according to `SPEC.md`:

1. Ingestion pipeline
2. Retrieval and chat
3. Project/document UI
4. Chat with source cards
5. PDF viewer with highlights

## Example data

Place local test PDFs in `example_data/` (gitignored). This folder is not committed to the repository.
