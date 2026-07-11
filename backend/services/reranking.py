import re
from functools import lru_cache

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from config import settings

# HuggingFace's chunked "xet" download backend does frequent small staged
# writes that hang on this project's exFAT external drive (same root cause
# as the venv corruption earlier) — the model cache stays on internal disk,
# same as the venv itself. It's small (~470MB for the configured reranker).

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


@lru_cache(maxsize=1)
def _get_cross_encoder() -> CrossEncoder:
    return CrossEncoder(settings.reranker_model)


def bm25_rank_ids(query: str, ids: list[str], documents: list[str]) -> list[str]:
    """Ranks chunk ids by keyword (BM25) match against the query, best first.

    Catches cases where the answer shares near-verbatim terminology with the
    question but the embedding model still under-ranks it semantically.
    """
    if not documents:
        return []
    bm25 = BM25Okapi([_tokenize(doc) for doc in documents])
    scores = bm25.get_scores(_tokenize(query))
    order = sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)
    return [ids[i] for i in order]


def reciprocal_rank_fusion(*rankings: list[str], k: int = 60) -> list[str]:
    """Merges multiple best-first id rankings into one, best first."""
    fused_scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking):
            fused_scores[item_id] = fused_scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused_scores, key=lambda item_id: fused_scores[item_id], reverse=True)


def rerank_ids(query: str, ids: list[str], documents: list[str], top_k: int) -> list[str]:
    """Cross-encoder scores each (query, chunk) pair directly and returns the
    best top_k ids, best first — catches cases where two candidates share
    similar vocabulary but only one actually answers the question.
    """
    if not documents:
        return []
    model = _get_cross_encoder()
    scores = model.predict([(query, doc) for doc in documents])
    order = sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)
    return [ids[i] for i in order[:top_k]]
