import re
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings
from services.norm_identity import parse_identity


def get_project_storage_dir(project_id: str) -> Path:
    path = settings.storage_dir / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_project_documents_dir(project_id: str) -> Path:
    path = get_project_storage_dir(project_id) / "documents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_chroma_client(project_id: str) -> chromadb.ClientAPI:
    chroma_path = get_project_storage_dir(project_id) / "chroma"
    chroma_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(chroma_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_collection(project_id: str):
    client = get_chroma_client(project_id)
    return client.get_or_create_collection(
        name=f"project_{project_id.replace('-', '_')}",
        metadata={"hnsw:space": "cosine"},
    )


# A project's collection is read whole on every query (services/llm.py caches
# it), so the query side needs to know when a write has made that copy stale.
# Chroma exposes no cheap change token: count() misses reference enrichment,
# which rewrites a chunk's indexed text in place and leaves both the id set and
# the count untouched. This counter is bumped by every write path instead.
#
# In-process state is sufficient because the app runs a single uvicorn worker
# -- pinned deliberately in the Dockerfile, because a second worker duplicates
# the corpus and the cross-encoder and does not fit the instance. A multi-worker
# deployment would need this in shared storage.
_collection_versions: dict[str, int] = {}


def bump_collection_version(project_id: str) -> None:
    """Marks a project's collection as changed. Call after any write to it."""
    _collection_versions[project_id] = _collection_versions.get(project_id, 0) + 1


def get_collection_version(project_id: str) -> int:
    return _collection_versions.get(project_id, 0)


def init_project_storage(project_id: str) -> None:
    get_project_documents_dir(project_id)
    get_collection(project_id)


def extract_norm_reference(filename: str, first_page_text: str = "") -> str | None:
    # A recognised publisher states its own identity on the cover, which is
    # more precise than pattern-matching a name out of arbitrary text — it
    # distinguishes an amendment (EN 1990/A1) from the norm it amends.
    # Everything else keeps the original behaviour below.
    identity = parse_identity(filename, first_page_text)
    if identity:
        return identity.reference

    patterns = [
        r"(DIN\s*EN?\s*\d+(?:-\d+)*)",
        r"(ÖNORM\s*[A-Z]?\s*\d+(?:-\d+)*)",
        r"(EN\s*\d+(?:-\d+)*)",
        r"(LBO\s*[A-Za-z]*)",
        r"(Eurocode\s*\d+)",
    ]
    for text in (filename, first_page_text):
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return re.sub(r"\s+", " ", match.group(1)).strip()
    stem = Path(filename).stem
    return stem if stem else None
