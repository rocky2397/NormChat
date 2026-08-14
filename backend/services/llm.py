import difflib
import re
from dataclasses import dataclass, field

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from config import settings
from models.chat import ChatResponse, SourceChunk
from services.embeddings import get_embeddings
from services.query_expansion import expand_query
from services.norm_identity import normalize_reference_text
from services.reference_resolution import (
    _reference_matches_document,
    extract_clause_references,
)
from services.reranking import bm25_rank_ids, reciprocal_rank_fusion, rerank_ids
from services.storage import get_collection

SYSTEM_PROMPT = """Du bist ein technischer Assistent für Bauingenieure und Architekten in der DACH-Region.
Beantworte Fragen ausschließlich auf Basis des bereitgestellten Kontexts aus Normdokumenten.

Regeln:
- Verwende kein Allgemeinwissen. Nur der Kontext zählt.
- Wenn der Kontext keine klare Antwort enthält, sage das ausdrücklich.
- Verweise immer auf die konkrete Klausel oder Abschnittsnummer, falls im Kontext vorhanden.
- Wenn du dich auf eine Quelle beziehst, nenne die Norm-Bezeichnung oder den
  Dokumentnamen (z. B. "DIN 4102-2"), niemals die interne Markierung
  "[Quelle N]" aus dem Kontext — diese ist nur zur internen Zuordnung gedacht
  und wird dem Nutzer nicht angezeigt.
- Wenn sich Angaben aus verschiedenen Teilen derselben Normenreihe
  unterscheiden (z. B. EN 1992-1-1 gegenüber EN 1992-2), wähle nicht
  stillschweigend einen Wert aus. Nenne beide Werte, ordne jeden ausdrücklich
  seinem Teil zu und gib an, für welchen Anwendungsbereich der jeweilige Teil
  laut Kontext gilt. Wenn der Kontext den Anwendungsbereich nicht hergibt,
  sage das und überlasse die Entscheidung dem Fachingenieur.
- Halte die Antwort präzise und technisch. Der Nutzer ist Fachingenieur.
- Antworte auf Deutsch, sofern die Frage auf Deutsch gestellt wird.
- Schreibe Formeln immer in LaTeX, eingeschlossen in \\( ... \\) für Inline-Formeln
  oder \\[ ... \\] für abgesetzte Formeln (z. B. \\( f_{cd} = \\alpha_{cc} \\cdot f_{ck} / \\gamma_c \\))."""


def _format_context(sources: list[SourceChunk]) -> str:
    blocks = []
    for i, source in enumerate(sources, start=1):
        ref = source.norm_reference or source.filename
        if source.edition:
            ref = f"{ref} ({source.edition})"
        blocks.append(
            f"[Quelle {i}] {ref}, Seite {source.page_number}:\n{source.chunk_text}"
        )
    return "\n\n".join(blocks)


# A label is "Quelle"/"Quellen" followed by one or more indices, which the
# model writes in several shapes — bracketed as instructed ("[Quelle 1]"), but
# also parenthesised prose ("(siehe Quelle 1 und 2)") and bare ("Quelle 3").
# The bracketed form is consumed whole; the others keep their surrounding
# words so the sentence still reads.
_INDEX_LIST = r"\d+(?:\s*(?:,|und|and|&|bis)\s*\d+)*"
_BRACKETED_LABEL = re.compile(rf"\[\s*Quellen?\s+(?P<indices>{_INDEX_LIST})\s*\]")
_BARE_LABEL = re.compile(rf"\bQuellen?\s+(?P<indices>{_INDEX_LIST})")


def _replace_citation_labels(answer: str, sources: list[SourceChunk]) -> str:
    """The model is instructed to cite documents by name, but LLM output is
    non-deterministic — this is a deterministic backstop that rewrites any
    source label it emits anyway into the matching document's name, so the
    internal indexing scheme never leaks into the user-visible answer.

    Matching only "[Quelle N]" was not enough: an eval run produced
    "(siehe Quelle 1 und 2)", which reached the user untouched.
    """

    def _named(match: re.Match) -> str:
        index = int(match.group(0))
        if 1 <= index <= len(sources):
            source = sources[index - 1]
            return source.norm_reference or source.filename
        return match.group(0)

    def _rewrite(match: re.Match) -> str:
        indices = match.group("indices")
        # Substituting inside the index list preserves the model's own
        # separators, so "1 und 2" and "1, 2, 3" keep reading naturally.
        named = re.sub(r"\d+", _named, indices)
        if named == indices:
            # Nothing resolved (every index out of range) — leave the label
            # exactly as it was rather than mangling it into bare numbers.
            return match.group(0)
        return named

    answer = _BRACKETED_LABEL.sub(_rewrite, answer)
    return _BARE_LABEL.sub(_rewrite, answer)


# A national annex states its rules as a delta against the European norm,
# addressing the parent clause by number: "Festlegung zu ÖNORM EN 1992-1-1,
# Abschnitt 3.1.6(1)P — Der empfohlene Wert wird übernommen." Such a chunk
# carries almost no domain vocabulary, so neither the embedding nor BM25 can
# reach it from a question phrased in words, and three of five reference
# questions missed the clause that actually decided the answer
# (eval/runs/2026-08-06-front-matter-and-labels.md). The clause number is the
# one token it does share, so it is looked up literally.
_CLAUSE_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)+)")
# Four, not three, because the parent clauses are walked in retrieval order
# and a question's *central* clause is not always the first one found: on Q3
# (Querkraft) the reranker put a Verformungen chunk above the §6.2.3 one, so
# §6.2.3 is the fourth clause walked and its Austrian modification fell
# outside a budget of three. Measured on the reference set: at 4 the register
# fragments stay at 1 and context grows 13.4 -> 14.0 chunks; at 5 and above
# register fragments start returning (2, then 3). This is tuning against
# seven questions and should be re-derived when the set grows.
CLAUSE_LOOKUP_LIMIT = 4


def _leading_clause_numbers(texts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(clause number, owning document id) for what the first pass landed on.

    Reads the heading the chunker prepends to every piece of a clause, so a
    chunk from the middle of §6.2 still reports 6.2. The owning document
    travels with the number because the lookup must exclude that document
    and only that one.
    """
    seen: list[tuple[str, str]] = []
    numbers: set[str] = set()
    for text, document_id in texts:
        match = _CLAUSE_HEADING.match(text)
        if match and match.group(1) not in numbers:
            numbers.add(match.group(1))
            seen.append((match.group(1), document_id))
    return seen


_NORM_PART = re.compile(r"\b(\d{4}(?:-\d+)*)\b")


def _norm_part(norm_reference: str | None) -> str | None:
    """The part number a document belongs to — 1992-1-1, or 1992-2.

    A European norm and its national annex share a part (EN 1992-1-1 and
    B 1992-1-1 are both 1992-1-1); different parts of the same family are
    different documents about different things.
    """
    match = _NORM_PART.search(norm_reference or "")
    return match.group(1) if match else None


def _parts_in_conflict(sources: list[SourceChunk]) -> dict[str, list[str]]:
    """Norm families for which more than one part was retrieved.

    Different parts of one Eurocode legitimately give different values for
    the same symbol — EN 1992-1-1 recommends α_cc = 1,0 for buildings while
    EN 1992-2 recommends 0,85 for bridges. With both in context and nothing
    saying which governs, the answer flipped between runs on context ordering
    alone (eval/runs/2026-08-06-compound-expansion.md). Detected here so the
    model is told to attribute and contrast rather than quietly pick one.
    """
    by_family: dict[str, set[str]] = {}
    for source in sources:
        family = _norm_family(source.norm_reference)
        part = _norm_part(source.norm_reference)
        if family and part:
            by_family.setdefault(family, set()).add(part)
    return {f: sorted(parts) for f, parts in by_family.items() if len(parts) > 1}


_NORM_FAMILY = re.compile(r"\b(\d{4})\b")


def _norm_family(norm_reference: str | None) -> str | None:
    """The Eurocode number a document belongs to — 1992 for EN and B 1992-1-1.

    Clause numbers only mean anything inside one family. Without this scope,
    looking up EN 1992-1-1 §9.2.2 (Querkraftbewehrung) also matched
    ÖNORM B 1991-1-3 §9.2.2 (Schneeverwehungen), putting a snow-load clause
    into a shear question.
    """
    match = _NORM_FAMILY.search(norm_reference or "")
    return match.group(1) if match else None


def _states_modification(
    text: str, clause: str, owner_reference: str | None = None
) -> bool:
    """Whether this chunk states a modification *of* that clause, rather than
    merely containing its number.

    The distinction is the difference between a rule and an index. Every
    ÖNORM B annex opens with "Tabelle 1 — Wahlmöglichkeiten", a register
    listing every EN clause that carries a national choice. It therefore
    contains every clause number and matches every lookup, while the clause
    that states the actual deviation matches exactly one — so on corpus
    order the register won, and won repeatedly. Measured: for §6.1 it was one
    of 49 candidates that merely mention the number, against 6 that state a
    modification (eval/runs/2026-08-13-*.md).

    Reuses the resolver's own parser, which is what delta admission already
    trusts to decide the same question, and so recognises "Festlegung zu",
    "Ergänzung zur" and "Erläuterung zur" alike. Prefix matching runs both
    ways: a chunk may address §3.1.6(1)P while the retrieved parent is
    headed §3.1.6, or address §6.2 while the parent is headed §6.2.3.

    `owner_reference` is the candidate's own norm. It is what lets a German
    national annex be recognised at all: those state "NDP zu 6.2.3" without
    naming the norm, and the reference only resolves against the parent the
    annex's own designation identifies.
    """
    for reference in extract_clause_references(text, owner_reference):
        if reference.clause.startswith(clause) or clause.startswith(reference.clause):
            return True
    return False


def _clause_reference_ids(
    clause: str,
    exclude_document_ids: set[str],
    ids: list[str],
    id_to_doc: dict[str, str],
    id_to_meta: dict[str, dict],
    family: str | None = None,
) -> list[str]:
    """Chunks in *other* documents that cite this clause by number, best first.

    Only the document the clause itself came from is excluded — a norm cites
    its own clauses constantly, so including it would just return more of the
    same passage. Excluding every document already present in the results
    instead is too coarse: a single front-matter chunk of ÖNORM B 1992-1-1
    ranking in the first pass would then bar its §6.1.4 from the second,
    which is the exact clause the lookup exists to reach.

    Ordering is a preference, not a filter: chunks that state a modification
    of the clause come first, everything else keeps corpus order behind them.
    Preferring rather than rejecting means a corpus whose annexes phrase
    deviations in a way the resolver does not recognise degrades to the
    previous behaviour instead of returning nothing. `sorted` is stable, so
    the result stays deterministic.
    """
    # Bounded on both sides so 3.1.6 does not match inside 13.1.6 or 3.1.60,
    # while still matching the "3.1.6(1)P" form the annexes use.
    pattern = re.compile(rf"(?<![\d.]){re.escape(clause)}(?![\d])")
    candidates = [
        cid
        for cid in ids
        if id_to_meta[cid]["document_id"] not in exclude_document_ids
        and (family is None or _norm_family(id_to_meta[cid].get("norm_reference")) == family)
        and pattern.search(id_to_doc[cid])
    ]
    return sorted(
        candidates,
        key=lambda cid: not _states_modification(
            id_to_meta[cid].get("raw_text") or id_to_doc[cid],
            clause,
            id_to_meta[cid].get("norm_reference"),
        ),
    )


def _page_key(meta: dict) -> tuple[str, int]:
    """The unit a citation is rendered at: one document, one page."""
    try:
        return (meta["document_id"], int(meta["page_number"]))
    except (KeyError, TypeError, ValueError):
        return (meta.get("document_id", ""), -1)


@dataclass
class RetrievalTrace:
    """Where every chunk id ranked at each stage of one retrieve_sources()
    call, keyed by the stage names in PIPELINE_STAGES.

    Filled in only when a caller passes an instance in. Recording is
    write-only — it must never influence the ranking itself; a test asserts
    the sources are identical with and without a trace attached. Exists for
    backend/eval/retrieval_probe.py, which reports where the gold chunks
    rank at each stage.

    Stages record themselves as they run rather than being snapshotted by
    hand at chosen points in the flow. That is what fixes the previous
    reading of "reranked": the snapshot sat after delta admission, so the
    column named for the reranker reported the reranker plus whatever
    admission had added.
    """

    stages: dict[str, list[str]] = field(default_factory=dict)
    # Metadata for every chunk id in the collection, so a consumer can map
    # any ranked id to (norm_reference, page_number) without re-querying.
    id_to_meta: dict[str, dict] = field(default_factory=dict)

    def record(self, stage: str, ids: list[str]) -> None:
        self.stages[stage] = list(ids)

    def ids(self, stage: str) -> list[str]:
        return self.stages.get(stage, [])

    # The historical attribute names, kept as views so existing callers and
    # run notes keep working.
    @property
    def vector_ids(self) -> list[str]:
        return self.ids("dense")

    @property
    def bm25_ids(self) -> list[str]:
        return self.ids("lexical")

    @property
    def fused_ids(self) -> list[str]:
        return self.ids("fused")

    @property
    def reranked_ids(self) -> list[str]:
        return self.ids("reranked")

    @property
    def deltas_admitted_ids(self) -> list[str]:
        return self.ids("deltas_admitted")

    @property
    def final_ids(self) -> list[str]:
        return self.ids("final")


# How deep into the fused ranking a delta clause may sit and still be
# admitted, and how many may be admitted per question. Deep enough that a
# clause the fusion genuinely favoured is not lost to an arbitrary cut,
# shallow enough that a delta which merely shares a number with something
# retrieved cannot ride in on it.
ANNEX_DELTA_FUSED_DEPTH = 25
ANNEX_DELTA_ADMIT_LIMIT = 3


def _covered_parent_clauses(
    final_ids: list[str], id_to_doc: dict[str, str], id_to_meta: dict[str, dict]
) -> set[tuple[str, str]]:
    """(document designation, clause number) the reranked results already cover."""
    covered: set[tuple[str, str]] = set()
    for cid in final_ids:
        meta = id_to_meta[cid]
        reference = meta.get("norm_reference")
        text = meta.get("raw_text") or id_to_doc[cid]
        heading = _CLAUSE_HEADING.match(text)
        if reference and heading:
            covered.add((reference, heading.group(1)))
    return covered


def _delta_parent_is_covered(
    raw_text: str, covered: set[tuple[str, str]]
) -> bool:
    """Whether this delta modifies a clause the reranked results landed on.

    A delta names the clause it modifies. Admitting one whose parent nobody
    retrieved would inject an unrelated rule: an early version admitted any
    enriched chunk in the fused pool, and a question about which timber fire
    norms apply came back citing ÖNORM B 1995-1-1 — a sibling annex whose
    parent was never retrieved — while failing to name B 1995-1-2, the one
    the question was about.

    Prefix matching in both directions, because a delta may address
    §3.1.6(1)P while the retrieved parent chunk is headed §3.1.6, or address
    §6.2 while the parent chunk is headed §6.2.3.
    """
    for reference in extract_clause_references(raw_text):
        for covered_reference, covered_clause in covered:
            # The stored reference carries its publisher ("ÖNORM EN 1992-1-1")
            # while a citation names only the norm ("EN 1992-1-1"), and the
            # match must not let EN 1992-1 satisfy EN 1992-1-1. That is
            # exactly what the resolver's own matcher already decides.
            if not _reference_matches_document(reference, covered_reference):
                continue
            if covered_clause.startswith(reference.clause) or reference.clause.startswith(
                covered_clause
            ):
                return True
    return False


def _admit_annex_deltas(
    final_ids: list[str],
    fused_ids: list[str],
    id_to_doc: dict[str, str],
    id_to_meta: dict[str, dict],
    limit: int = ANNEX_DELTA_ADMIT_LIMIT,
    depth: int = ANNEX_DELTA_FUSED_DEPTH,
) -> list[str]:
    """Re-admits national-annex delta clauses the cross-encoder discarded.

    A delta states its rule as a reference — "Festlegung zu ÖNORM
    EN 1992-1-1, Abschnitt 3.1.6(1)P — Der empfohlene Wert wird übernommen."
    Relevance by reference is not something a passage-ranking cross-encoder
    represents: it scores (question, chunk) pairs, and that text shares
    nothing with a question about concrete compressive strength.

    Measured rather than assumed. With index-time enrichment the clause
    reaches fused rank 3 and the reranker still drops it from a top ten, and
    swapping in a model 4.8x larger with 16x the context moved reranked
    recall from 3/10 to 4/10 while dropping that same clause. The mismatch
    is in the training objective, not the capacity, so these chunks are
    admitted on their fused rank rather than scored again.

    Enrichment is the signal: services/reference_resolution.py records
    raw_text only on chunks whose reference it actually resolved, so this
    never fires on an unenriched project and never on ordinary prose.
    """
    covered = _covered_parent_clauses(final_ids, id_to_doc, id_to_meta)
    if not covered:
        return list(final_ids)

    admitted = list(final_ids)
    already = set(final_ids)
    for cid in fused_ids[:depth]:
        if len(admitted) - len(final_ids) >= limit:
            break
        raw_text = id_to_meta[cid].get("raw_text")
        if cid in already or not raw_text:
            continue
        if not _delta_parent_is_covered(raw_text, covered):
            continue
        already.add(cid)
        admitted.append(cid)
    return admitted


# ---------------------------------------------------------------------------
# The retrieval pipeline, written out as stages.
#
# Each stage takes what it reads and returns a new list; none mutates a list
# another stage owns, and each declares its own budget as a parameter. That
# is not decoration. Every defect found in this path so far came from stages
# sharing state they never declared — the clause lookup capping itself on a
# total that delta admission had already grown, and the same lookup re-adding
# a page an earlier stage had placed
# (eval/runs/2026-08-13-budget-separation-and-index-cache.md). Written this
# way, neither is expressible.
# ---------------------------------------------------------------------------

# Stage names in pipeline order. The trace records under these names and the
# eval probe builds its columns from them, so adding a stage adds a column
# rather than requiring the probe to be edited to match.
#
# The first five are the historical column names and must keep their meaning:
# every run note under eval/runs/ is keyed to them. "deltas_admitted" is new,
# and splits a boundary that used to be invisible — "reranked" previously
# reported the list *after* delta admission, so the column named for the
# reranker was not showing the reranker's output.
PIPELINE_STAGES = (
    "dense",
    "lexical",
    "fused",
    "reranked",
    "deltas_admitted",
    "final",
)


@dataclass(frozen=True)
class Corpus:
    """Every chunk of one project, read once per request.

    BM25 needs the whole corpus for term-frequency statistics, so this is
    loaded entire rather than queried. It is the O(corpus) cost the retrieval
    path is currently built on, and the reason a stage seam here matters more
    than the others.
    """

    ids: list[str]
    documents: list[str]
    id_to_doc: dict[str, str]
    id_to_meta: dict[str, dict]

    def meta(self, chunk_id: str) -> dict:
        return self.id_to_meta[chunk_id]

    def text(self, chunk_id: str) -> str:
        return self.id_to_doc[chunk_id]


def _load_corpus(collection) -> Corpus:
    all_chunks = collection.get(include=["documents", "metadatas"])
    ids = all_chunks["ids"]
    documents = all_chunks["documents"]
    return Corpus(
        ids=ids,
        documents=documents,
        id_to_doc=dict(zip(ids, documents)),
        id_to_meta=dict(zip(ids, all_chunks["metadatas"])),
    )


def _query_plan(question: str) -> list[str]:
    """The question, plus any expansion probes.

    The probes are retrieval inputs and nothing else: reranking, the
    answering context and highlighting all work on the question and on real
    chunk text. With expansion off, or failed, this is just [question].
    """
    return [question, *expand_query(question)]


def _dense_ranking(collection, embeddings, query: str, pool_size: int) -> list[str]:
    results = collection.query(
        query_embeddings=[embeddings.embed_query(query)],
        n_results=pool_size,
        include=["documents", "metadatas"],
    )
    return results["ids"][0]


def _lexical_ranking(corpus: Corpus, query: str, pool_size: int) -> list[str]:
    """Catches chunks that share the question's exact terminology but rank
    low on pure embedding similarity."""
    return bm25_rank_ids(query, corpus.ids, corpus.documents)[:pool_size]


def _fuse(rankings: list[list[str]], pool_size: int) -> list[str]:
    return reciprocal_rank_fusion(*rankings)[:pool_size]


def _rerank(question: str, candidates: list[str], corpus: Corpus, top_k: int) -> list[str]:
    return rerank_ids(question, candidates, [corpus.text(c) for c in candidates], top_k)


def _clause_lookup(
    selected: list[str], corpus: Corpus, limit: int = CLAUSE_LOOKUP_LIMIT
) -> list[str]:
    """Whatever clauses the first pass landed on, pull in the places other
    documents modify them.

    Appended rather than substituted: this adds the national deviation to the
    rule, it does not replace it. The budget is counted here and nowhere else,
    and a page already represented anywhere in `selected` is skipped — a
    citation is a page, so two chunks of one page open the same source card on
    the same highlight and the second buys the user nothing.

    That page rule applies only to candidates that do not state a
    modification of the clause being looked up. Two distinct clauses can
    share a page: ÖNORM B 1992-1-1 p. 21 carries §9.1.1, a bending
    Ergänzung, and §9.2.4, the Querkraft Festlegung — and parent clause 6.1
    is walked before 6.2.3, so a blanket page rule let the bending clause
    take the page and silently locked out the shear clause the question was
    about. A chunk that answers *this* clause is admitted even onto a page
    already represented; register fragments, which state no modification,
    still are not.
    """
    already = set(selected)
    covered_pages = {_page_key(corpus.meta(cid)) for cid in selected}
    retrieved = [(corpus.text(cid), corpus.meta(cid)["document_id"]) for cid in selected]
    owner_family = {
        corpus.meta(cid)["document_id"]: _norm_family(corpus.meta(cid).get("norm_reference"))
        for cid in selected
    }

    admitted = list(selected)
    looked_up = 0
    for clause, owner_id in _leading_clause_numbers(retrieved):
        for cid in _clause_reference_ids(
            clause,
            {owner_id},
            corpus.ids,
            corpus.id_to_doc,
            corpus.id_to_meta,
            owner_family.get(owner_id),
        ):
            if cid in already:
                continue
            meta = corpus.meta(cid)
            page = _page_key(meta)
            if page in covered_pages and not _states_modification(
                meta.get("raw_text") or corpus.text(cid),
                clause,
                meta.get("norm_reference"),
            ):
                continue
            already.add(cid)
            covered_pages.add(page)
            admitted.append(cid)
            looked_up += 1
            break  # one modifying clause per parent clause is enough
        if looked_up >= limit:
            break
    return admitted


def _assemble(selected: list[str], corpus: Corpus) -> list[SourceChunk]:
    sources: list[SourceChunk] = []
    for cid in selected:
        meta = corpus.meta(cid)
        sources.append(
            SourceChunk(
                document_id=meta["document_id"],
                filename=meta["source_filename"],
                page_number=int(meta["page_number"]),
                # The indexed text may carry appended parent-clause headings
                # (services/reference_resolution.py); everything user-facing —
                # display, LLM context, excerpt grounding — must see only text
                # that exists on the cited page, so the original is read back
                # from raw_text. Collections indexed before enrichment existed
                # carry no raw_text; their stored text is already original.
                chunk_text=meta.get("raw_text") or corpus.text(cid),
                norm_reference=meta.get("norm_reference") or None,
                edition=meta.get("edition") or None,
            )
        )
    return sources


def retrieve_sources(
    project_id: str, question: str, trace: RetrievalTrace | None = None
) -> list[SourceChunk]:
    """Runs the pipeline and records it. The stages decide; this only orders
    them and reports what each returned."""
    collection = get_collection(project_id)
    total = collection.count()
    if total == 0:
        return []
    pool_size = min(settings.retrieval_candidate_pool, total)

    corpus = _load_corpus(collection)
    embeddings = get_embeddings()

    rankings: list[list[str]] = []
    for query in _query_plan(question):
        rankings.append(_dense_ranking(collection, embeddings, query, pool_size))
        rankings.append(_lexical_ranking(corpus, query, pool_size))

    def record(stage: str, ids: list[str]) -> list[str]:
        """Records a stage's output and returns it unchanged.

        Recording happens at the call site of the stage it names, so a stage
        cannot be reported under the wrong name and a new stage cannot be
        added without appearing in the trace.
        """
        if trace is not None:
            trace.record(stage, ids)
        return ids

    # The dense and lexical rows report the question itself, the first two
    # rankings: expansion probes are auxiliary inputs to the fusion, and
    # folding them in would change what a "dense rank" means depending on a
    # feature flag and make probe runs incomparable across arms.
    record("dense", rankings[0])
    record("lexical", rankings[1])

    fused = record("fused", _fuse(rankings, pool_size))
    reranked = record("reranked", _rerank(question, fused, corpus, settings.top_k_chunks))
    with_deltas = record(
        "deltas_admitted",
        _admit_annex_deltas(reranked, fused, corpus.id_to_doc, corpus.id_to_meta),
    )
    final = record("final", _clause_lookup(with_deltas, corpus))

    if trace is not None:
        trace.id_to_meta = dict(corpus.id_to_meta)

    return _assemble(final, corpus)


def generate_answer(question: str, sources: list[SourceChunk]) -> str:
    if not sources:
        return (
            "Im hochgeladenen Dokumentenbestand dieses Projekts konnte keine "
            "relevante Passage gefunden werden."
        )

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    context = _format_context(sources)
    llm = ChatOpenAI(
        model=settings.openai_model,
        openai_api_key=settings.openai_api_key,
        temperature=0,
    )

    # The system rule alone is easy for the model to overlook when the parts
    # sit many chunks apart, so the specific collision is named here too.
    conflicts = _parts_in_conflict(sources)
    warning = ""
    if conflicts:
        listed = "; ".join(
            f"Normenreihe {family}: Teile {', '.join(parts)}"
            for family, parts in sorted(conflicts.items())
        )
        warning = (
            f"\n\nAchtung: Der Kontext enthält mehrere Teile derselben Normenreihe "
            f"({listed}). Falls sich deren Angaben unterscheiden, nenne beide, ordne "
            f"jede Angabe ihrem Teil zu und gib den jeweiligen Anwendungsbereich an, "
            f"statt einen Wert auszuwählen."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Kontext:\n{context}\n\n"
                f"Frage: {question}\n\n"
                "Beantworte die Frage basierend ausschließlich auf dem Kontext."
                f"{warning}"
            ),
        },
    ]
    response = llm.invoke(messages)
    return response.content.strip()


class _SourceExcerpt(BaseModel):
    source_index: int = Field(description="1-based [Quelle N] number this excerpt belongs to")
    excerpt: str = Field(
        description="The exact, verbatim, character-for-character substring copied "
        "from that source's text that the answer actually relied on — a short "
        "phrase or single sentence, not a paraphrase and not the whole passage."
    )


class _CitationExcerpts(BaseModel):
    excerpts: list[_SourceExcerpt] = Field(
        description="One entry per source that genuinely contributed to the answer. "
        "Omit sources that were only tangentially retrieved and not actually used."
    )


def extract_citation_excerpts(
    question: str, answer: str, sources: list[SourceChunk]
) -> dict[int, str]:
    """Asks the model which exact excerpt it relied on per source, for precise
    PDF highlighting. Isolated from generate_answer() on purpose: this is a
    locate-existing-text hint, not an assertion of fact, so if the model
    misquotes or this call fails outright, downstream search-on-page simply
    won't find it and we fall back to the raw chunk_text — it never affects
    the actual answer shown to the user.
    """
    if not sources or not settings.openai_api_key:
        return {}

    context = _format_context(sources)
    llm = ChatOpenAI(
        model=settings.openai_model,
        openai_api_key=settings.openai_api_key,
        temperature=0,
    )
    structured_llm = llm.with_structured_output(_CitationExcerpts)

    prompt = (
        f"Frage: {question}\n\n"
        f"Antwort: {answer}\n\n"
        f"Kontext (nummerierte Quellen):\n{context}\n\n"
        "Gib für jede Quelle, die tatsächlich zur obigen Antwort beigetragen hat, "
        "das exakte, wortwörtliche Zitat aus dem jeweiligen Quellentext zurück, auf "
        "das sich die Antwort stützt. Das Zitat muss zeichengenau im Quellentext "
        "vorkommen (keine Paraphrase) und kurz sein (ein Satz oder eine Kernaussage, "
        "nicht der ganze Abschnitt). Quellen ohne tatsächlichen Beitrag weglassen."
    )

    try:
        result = structured_llm.invoke(prompt)
    except Exception:
        return {}

    return {e.source_index: e.excerpt for e in result.excerpts}


def _sliding_windows(chunk_text: str, max_lines: int = 3) -> list[str]:
    raw_lines = [line.strip() for line in chunk_text.split("\n") if line.strip()]
    windows = []
    for size in range(1, max_lines + 1):
        for start in range(len(raw_lines) - size + 1):
            windows.append(" ".join(raw_lines[start : start + size]))
    return windows


def _ground_excerpt(excerpt: str, chunk_text: str, threshold: float = 0.35) -> str | None:
    """Despite instructions, the model tends to paraphrase/clean up its quoted
    excerpt rather than copy it character-for-character (confirmed in
    testing — PyMuPDF's on-page search then finds nothing). This finds the
    closest REAL span of chunk_text — a window of 1-3 consecutive raw PDF
    lines, since the target sentence is often split across several by the
    page's own line wrapping — so what actually gets searched for is
    guaranteed to be text that exists verbatim in the source.
    """
    if not excerpt:
        return None
    candidates = _sliding_windows(chunk_text)
    if not candidates:
        return None
    best_score, best_candidate = max(
        (difflib.SequenceMatcher(None, excerpt, c).ratio(), c) for c in candidates
    )
    return best_candidate if best_score >= threshold else None


def chat(project_id: str, question: str) -> ChatResponse:
    sources = retrieve_sources(project_id, question)
    answer = generate_answer(question, sources)
    excerpts = extract_citation_excerpts(question, answer, sources)
    for i, source in enumerate(sources, start=1):
        raw_excerpt = excerpts.get(i)
        source.highlight_snippet = (
            _ground_excerpt(raw_excerpt, source.chunk_text) if raw_excerpt else None
        )
    answer = _replace_citation_labels(answer, sources)
    return ChatResponse(answer=answer, sources=sources)
