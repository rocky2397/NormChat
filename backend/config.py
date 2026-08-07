from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    database_url: str = "sqlite:///./normchat.db"
    storage_dir: Path = Path(__file__).parent / "storage"
    top_k_chunks: int = 10
    chunk_size: int = 512
    chunk_overlap: int = 64
    retrieval_candidate_pool: int = 100
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    # Index-time reference enrichment for national-annex delta clauses
    # (services/reference_resolution.py). Off by default so the retrieval
    # probe can measure both arms against the same corpus.
    reference_enrichment_enabled: bool = False

    auth_username: str = ""
    auth_password: str = ""
    session_secret: str = ""
    session_cookie_secure: bool = False


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
