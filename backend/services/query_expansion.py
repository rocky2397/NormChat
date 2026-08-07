"""Pre-retrieval sub-query decomposition.

A design question implies norm sub-topics whose vocabulary the question
itself never contains: Q2 asks about R60 fire design for a timber beam, but
the deciding content lives under "Abbrandtiefe" and "Restquerschnitt"
(EN 1995-1-2 §4.2.2) — terms the question does not say. Every retrieval
mechanism downstream works on terms already present in the query (dense
similarity, BM25 tokens, compound splitting), so none of them can bridge
that gap. This step asks a cheap model, before any embedding happens, for
the retrieval queries the steps of a norm answer would need.

The generated queries are retrieval probes and nothing else. They feed
extra rankings into reciprocal_rank_fusion() and are never stored, never
shown to the user, and never enter the answering context — everything the
user sees stays sourced from real chunks of real uploaded PDFs.
"""

import logging

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from config import settings

logger = logging.getLogger(__name__)


class _SubQueries(BaseModel):
    queries: list[str] = Field(
        description="Kurze, eigenständige Suchanfragen mit der Fachterminologie "
        "der Normen, je eine pro Teilschritt der Bemessung."
    )


_PROMPT = """Ein Fachingenieur stellt die folgende Frage an eine Sammlung von \
Baunormen (Eurocodes, DIN, ÖNORM):

Frage: {question}

Zerlege die Frage in die Teilschritte, die eine normgerechte Antwort abdecken \
müsste, und formuliere für jeden Teilschritt eine kurze Suchanfrage (2 bis 6 \
Wörter). Verwende die Fachterminologie, die die Norm für den jeweiligen \
Teilschritt benutzt — insbesondere Begriffe, die in der Frage selbst nicht \
vorkommen. Beispiel: eine Frage zur Heißbemessung eines Holzbauteils braucht \
Suchanfragen wie "Abbrandtiefe Bemessungswert" oder "ideeller Restquerschnitt", \
auch wenn die Frage diese Wörter nicht enthält. Gib 2 bis {max_queries} \
Suchanfragen zurück."""


def expand_query(question: str) -> list[str]:
    """Sub-queries to retrieve with alongside the question, [] on any failure.

    [] means "retrieve with the question alone" — exactly today's behaviour —
    so a model failure or timeout silently degrades instead of failing the
    request, which sits on the user's critical path.
    """
    if not settings.query_expansion_enabled:
        return []
    if not settings.openai_api_key:
        return []

    try:
        llm = ChatOpenAI(
            model=settings.query_expansion_model,
            openai_api_key=settings.openai_api_key,
            temperature=0,
            timeout=settings.query_expansion_timeout_seconds,
            # The langchain default of 2 retries would stack on the timeout
            # while the user waits; degrading to single-query retrieval is
            # cheaper than a second attempt.
            max_retries=0,
        )
        structured_llm = llm.with_structured_output(_SubQueries)
        result = structured_llm.invoke(
            _PROMPT.format(
                question=question, max_queries=settings.query_expansion_max_queries
            )
        )
    except Exception:
        logger.warning(
            "Query expansion failed for %r; falling back to single-query retrieval",
            question,
            exc_info=True,
        )
        return []

    seen: set[str] = {question.strip().lower()}
    queries: list[str] = []
    for query in result.queries:
        cleaned = query.strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            queries.append(cleaned)
    queries = queries[: settings.query_expansion_max_queries]
    # Logged so an eval run note can quote exactly what was probed.
    logger.info("Sub-queries for %r: %r", question, queries)
    return queries
