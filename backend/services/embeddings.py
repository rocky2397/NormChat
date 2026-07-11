from langchain_openai import OpenAIEmbeddings

from config import settings


def get_embeddings() -> OpenAIEmbeddings:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        openai_api_key=settings.openai_api_key,
    )
