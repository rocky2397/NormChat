import re
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings


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


def init_project_storage(project_id: str) -> None:
    get_project_documents_dir(project_id)
    get_collection(project_id)


def extract_norm_reference(filename: str, first_page_text: str = "") -> str | None:
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
