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


# German compounding defeats exact-token matching: an engineer asks about
# "Querkraftbemessung" and the clause is headed "Querkraft", which share no
# token at all. Measured on the reference questions — the EN 1992-1-1 §6.2
# chunks ranked 281st for the question as written and 5th for "Querkraft"
# (eval/runs/2026-08-06-clause-lookup.md).
MIN_COMPOUND_LENGTH = 12
MIN_PART_LENGTH = 5
MAX_PARTS_PER_TOKEN = 3


def _expand_compounds(tokens: list[str], vocabulary: set[str]) -> list[str]:
    """Adds the corpus words that a long query token is built from.

    The corpus supplies the vocabulary rather than a dictionary or a
    stemmer, so the parts are guaranteed to be terms the documents actually
    use; longest first, since "querkraft" carries more meaning than "kraft".

    Ties are broken alphabetically, and that matters more than it looks.
    Sorting on length alone left equal-length candidates in set iteration
    order, which Python randomises per process — so which parts survived the
    cut changed between runs, the BM25 query changed with them, and the same
    question returned different sources. It also made probe runs
    incomparable: a measured rank could move without anything being changed.
    """
    expanded = list(tokens)
    for token in tokens:
        if len(token) < MIN_COMPOUND_LENGTH:
            continue
        parts = sorted(
            (w for w in vocabulary if MIN_PART_LENGTH <= len(w) < len(token) and w in token),
            key=lambda w: (-len(w), w),
        )
        expanded.extend(parts[:MAX_PARTS_PER_TOKEN])
    return expanded


def bm25_rank_ids(query: str, ids: list[str], documents: list[str]) -> list[str]:
    """Ranks chunk ids by keyword (BM25) match against the query, best first.

    Catches cases where the answer shares near-verbatim terminology with the
    question but the embedding model still under-ranks it semantically.
    """
    if not documents:
        return []
    tokenized = [_tokenize(doc) for doc in documents]
    bm25 = BM25Okapi(tokenized)
    vocabulary = {word for doc in tokenized for word in doc}
    scores = bm25.get_scores(_expand_compounds(_tokenize(query), vocabulary))
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
