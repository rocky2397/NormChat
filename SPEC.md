# NormChat — Product Specification

## Overview

NormChat is a RAG-powered chat interface for construction professionals in the DACH region. It allows engineers and architects to upload their own norm PDFs (DIN, LBO, Eurocode, ÖNORM) and query them in natural language. The tool surfaces the exact passage within the original PDF that answers the question, keeps the engineer in control of the source material, and is scoped per project so teams work from the same document set.

The product is supportive, not replacing. It does not tell engineers what to do. It finds the right passage in the document they would have read anyway and shows it to them directly.

---

## Core User Story

An engineer is working on a hospital project in Bavaria. They need to know the fire protection wall requirements for a corridor. Instead of opening a 300-page DIN PDF and using Ctrl+F, they type a question into the chat. The tool returns a direct answer with the source passage highlighted inside the original PDF, including the exact page number and norm reference.

---

## Tech Stack

- **Frontend:** React (Vite), Tailwind CSS, PDF.js for PDF rendering and highlight overlay
- **Backend:** FastAPI (Python)
- **RAG Pipeline:** LangChain with a chunking strategy suited to structured norm documents
- **Vector Store:** ChromaDB (local, persistent per project)
- **Embeddings:** OpenAI text-embedding-3-small or a local alternative (configurable)
- **LLM:** OpenAI GPT-4o via API (configurable, swap-friendly)
- **File Storage:** Local filesystem per project, organised by project ID
- **Database:** SQLite for project and document metadata

---

## Application Structure

```
normchat/
├── backend/
│   ├── main.py                  # FastAPI app entry point
│   ├── routers/
│   │   ├── projects.py          # Project CRUD
│   │   ├── documents.py         # PDF upload and ingestion
│   │   └── chat.py              # Query endpoint
│   ├── services/
│   │   ├── ingestion.py         # PDF parsing, chunking, embedding, storage
│   │   ├── retrieval.py         # Query the vector store, return chunks with metadata
│   │   └── llm.py               # LLM call, prompt construction, answer formatting
│   ├── models/
│   │   ├── project.py           # Project schema
│   │   ├── document.py          # Document schema
│   │   └── chat.py              # Message schema
│   ├── db/
│   │   └── database.py          # SQLite setup via SQLAlchemy
│   └── storage/
│       └── [project_id]/        # Per-project PDF files and ChromaDB collections
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatPanel.jsx         # Chat input and message thread
│   │   │   ├── PDFViewer.jsx         # PDF.js viewer with highlight overlay
│   │   │   ├── SourceCard.jsx        # Cited passage card with page jump
│   │   │   ├── ProjectSidebar.jsx    # Project switcher and document list
│   │   │   └── DocumentUpload.jsx    # Drag-and-drop PDF upload
│   │   ├── pages/
│   │   │   ├── ProjectView.jsx       # Main working view
│   │   │   └── ProjectList.jsx       # Project overview and creation
│   │   ├── api/
│   │   │   └── client.js             # Axios instance, typed API calls
│   │   └── main.jsx
│   └── index.html
└── README.md
```

---

## Feature Specifications

### 1. Project Management

Each project has a name, an optional state (Bundesland), and a set of uploaded documents. Projects are isolated from each other. The vector store for each project only contains documents uploaded to that project.

Fields: `id`, `name`, `bundesland` (optional, e.g. Bayern, Berlin), `created_at`

On project creation, a ChromaDB collection and a local storage directory are initialised for that project ID.

### 2. Document Upload and Ingestion

Engineers upload PDFs via drag-and-drop or file picker. Supported document types include DIN norms, Landesbauordnungen, Eurocodes, and ÖNORM documents. Any PDF is accepted since the format is consistent.

On upload, the backend runs the following ingestion pipeline:

1. Extract text from PDF using `pdfplumber`, preserving page numbers per chunk
2. Chunk the text using a structure-aware strategy. Norm documents have numbered clauses (e.g. 4.2.1). Split on clause boundaries where detectable, with a fallback to fixed-size chunks of 512 tokens with 64-token overlap.
3. Embed each chunk using the configured embedding model
4. Store chunks in ChromaDB with metadata: `document_id`, `page_number`, `chunk_index`, `source_filename`, `norm_reference` (extracted from filename or first page if parseable)
5. Store document record in SQLite

### 3. Chat and Retrieval

The chat endpoint accepts a question and a project ID. It runs the following pipeline:

1. Embed the query
2. Retrieve the top 5 most relevant chunks from the project's ChromaDB collection
3. Pass the question and retrieved chunks to the LLM with a strict prompt
4. Return the answer, the source chunks, and metadata (document name, page number, chunk text)

The LLM prompt must include these instructions:

- Answer based only on the provided context. Do not use general knowledge.
- If the context does not contain a clear answer, say so explicitly.
- Always reference the specific clause or section number if present in the context.
- Keep the answer concise and technical. The user is a trained engineer.

The response object returned to the frontend must include:

```json
{
  "answer": "string",
  "sources": [
    {
      "document_id": "string",
      "filename": "string",
      "page_number": 12,
      "chunk_text": "string",
      "norm_reference": "string"
    }
  ]
}
```

### 4. PDF Viewer with Passage Highlight

When the engineer clicks a source citation, the PDF viewer opens the correct document at the correct page. The cited chunk text is highlighted visually within the PDF using a PDF.js text layer overlay.

The viewer must support:

- Jump to page from source card click
- Highlight the cited text passage on the correct page
- Navigation between pages
- Zoom in and out

The PDF is rendered from the local backend file endpoint, not re-uploaded. The backend serves the file at `/documents/{document_id}/file`.

### 5. Source Cards

Each answer is followed by source cards, one per retrieved chunk. Each card shows:

- Document filename and norm reference (e.g. DIN 4102-2)
- Page number
- A short excerpt of the cited passage (max 3 lines, truncated with ellipsis)
- A button to open the PDF viewer at that page

---

## Key Constraints and Rules

**Bring-your-own-PDF.** The application never bundles or redistributes norm content. Engineers upload PDFs they already have legal access to. The backend stores them locally within the project scope only.

**No hallucination tolerance.** The LLM is strictly grounded. If retrieved context is insufficient, the tool says so. It never generates an answer from general knowledge about norms.

**Citation is mandatory.** Every answer must include at least one source. An answer without a source card is a bug.

**Project isolation.** Queries never cross project boundaries. Each project has its own ChromaDB collection. There is no global search.

**Engineer-first language.** The UI uses standard technical German terminology where appropriate. Labels, placeholders, and messages should feel native to the construction domain, not generic SaaS copy.

**Stateless frontend.** No local storage or browser caching of document content. All state is server-side.

---

## Out of Scope for MVP

- User authentication and multi-user access control
- Cloud storage or deployment pipeline
- Norm change tracking or update alerts
- BIM or CAD tool integration
- ÖNORM support beyond basic PDF ingestion (Austrian norm structure may differ)
- Mobile layout

---

## Development Priorities

Build in this order:

1. Backend ingestion pipeline (upload, parse, chunk, embed, store)
2. Backend retrieval and chat endpoint
3. Frontend project and document management views
4. Frontend chat panel with source cards
5. PDF viewer with highlight overlay

The PDF viewer is the most technically complex component. Leave it for last and verify the retrieval quality first using the raw API before connecting the viewer.
