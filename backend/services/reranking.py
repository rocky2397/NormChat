import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
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


def _expand_compounds(tokens: list[str], vocabulary: frozenset[str] | set[str]) -> list[str]:
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


@dataclass(frozen=True)
class _LexicalIndex:
    bm25: BM25Okapi
    ids: tuple[str, ...]
    vocabulary: frozenset[str]


def _build_lexical_index(
    ids: tuple[str, ...], documents: Sequence[str]
) -> _LexicalIndex:
    tokenized = [_tokenize(doc) for doc in documents]
    return _LexicalIndex(
        bm25=BM25Okapi(tokenized),
        ids=ids,
        vocabulary=frozenset(word for doc in tokenized for word in doc),
    )


def _documents_digest(documents: Sequence[str]) -> str:
    """Content fingerprint of a corpus, computed without retaining it.

    Identity cannot come from the ids alone: reference enrichment rewrites a
    chunk's indexed text in place and leaves its id untouched, and a stale
    index would then rank text that no longer exists. Hashing streams over the
    documents and keeps sixteen bytes.
    """
    digest = hashlib.blake2b(digest_size=16)
    for document in documents:
        digest.update(document.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


@dataclass
class _CacheInfo:
    hits: int = 0
    misses: int = 0


class _LexicalIndexCache:
    """One slot, keyed by corpus *identity* rather than by the corpus itself.

    Building the index tokenizes the whole corpus, so it is built once per
    corpus rather than once per query -- with expansion on it was otherwise
    rebuilt five times for a single request.

    Holding it in an `lru_cache` keyed on (ids, documents) was correct and
    quietly expensive: the cache retained a reference to every chunk string it
    was built from. The next query loaded a fresh copy of the corpus from
    Chroma while the previous copy was still reachable through that key, so two
    full corpora were resident at once. On the 137-document DIN corpus that is
    roughly 800 MB of chunk text, which is what took the *second* query of a
    session over a 2 GB instance limit and killed the process.

    Keying on a digest keeps the invalidation behaviour exactly -- a changed
    id set or changed chunk text still rebuilds -- while letting the previous
    corpus be collected. The slot is emptied before a rebuild, so a rebuild
    never holds two tokenized corpora either.
    """

    def __init__(self) -> None:
        self._key: tuple[tuple[str, ...], str] | None = None
        self._index: _LexicalIndex | None = None
        self._info = _CacheInfo()

    def get(self, ids: tuple[str, ...], documents: Sequence[str]) -> _LexicalIndex:
        key = (ids, _documents_digest(documents))
        if self._index is not None and self._key == key:
            self._info.hits += 1
            return self._index
        # Drop the old index before building the new one.
        self._key = None
        self._index = None
        self._info.misses += 1
        index = _build_lexical_index(ids, documents)
        self._key = key
        self._index = index
        return index

    def clear(self) -> None:
        self._key = None
        self._index = None
        self._info = _CacheInfo()

    def info(self) -> _CacheInfo:
        return self._info


_lexical_index_cache = _LexicalIndexCache()


def _get_lexical_index(
    ids: tuple[str, ...], documents: Sequence[str]
) -> _LexicalIndex:
    return _lexical_index_cache.get(ids, documents)


# Kept so callers and tests keep the `lru_cache` surface they were written
# against.
_get_lexical_index.cache_clear = _lexical_index_cache.clear
_get_lexical_index.cache_info = _lexical_index_cache.info


def bm25_rank_ids(query: str, ids: list[str], documents: list[str]) -> list[str]:
    """Ranks chunk ids by keyword (BM25) match against the query, best first.

    Catches cases where the answer shares near-verbatim terminology with the
    question but the embedding model still under-ranks it semantically.
    """
    if not documents:
        return []
    index = _get_lexical_index(tuple(ids), documents)
    scores = index.bm25.get_scores(_expand_compounds(_tokenize(query), index.vocabulary))
    order = sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)
    return [index.ids[i] for i in order]


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
