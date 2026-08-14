"""Index-time enrichment for delta clauses that cite a parent norm by number.

A national annex states its rules as a delta against the European norm,
addressing the parent clause by number and carrying almost no domain
vocabulary of its own — ÖNORM B 1992-1-1 §6.1.4 reads, in full:
"Festlegung zu ÖNORM EN 1992-1-1:2015, Abschnitt 3.1.6(1)P — Der empfohlene
Wert wird übernommen." Neither the embedding nor BM25 can reach that from a
question phrased in words, because the chunk shares no words with the
question (docs/norm-graph.md, eval/runs/2026-08-06-current.md).

This pass resolves such references within the project and appends the
heading text of the parent clause to the indexed representation of the
chunk, so a question phrased in the vocabulary of the parent can reach the
delta. Resolution is lexical and deterministic — the appended heading is
real text lifted from a document already in the project, never
LLM-generated, because an LLM-written summary attached to a chunk becomes
text that looks like norm content but is not (SPEC.md: no hallucination
tolerance).

The enrichment changes what is *searched*, never what is *shown*: the
original chunk text is preserved in a raw_text metadata field, and display,
LLM context and excerpt grounding all read that field (services/llm.py).
Collections indexed before this change carry no raw_text and fall back to
the stored document text, which is unenriched.

Documents arrive in any order — the annex may be uploaded before its parent
— so this runs as a project-level pass after each successful ingestion,
re-resolving chunks whose references were previously unresolvable and
re-embedding only those that changed.
"""

import logging
import re
from dataclasses import dataclass

from services.embeddings import get_embeddings
from services.norm_identity import normalize_reference_text
from services.storage import get_collection

logger = logging.getLogger(__name__)


# A reference names the norm and addresses the clause by number:
# "ÖNORM EN 1992-1-1:2015, Abschnitt 3.1.6(1)P". Matched on flattened text
# because typeset references wrap across lines mid-reference and carry
# non-breaking spaces and hyphens (normalize_reference_text handles both).
#
# The clause requires a sub-level (3.1.6, not 3) to mirror CLAUSE_PATTERN in
# chunking — only sub-level clauses ever become chunk headings, so a
# top-level section reference has nothing to resolve against. The clause
# match stops before a paragraph marker like "(1)P", which addresses a
# paragraph *inside* the clause whose heading is being looked up, and before
# contents-page dot leaders ("4.4.1.2(3)......13") since a dot must be
# followed by a digit to extend the clause.
CLAUSE_REFERENCE_PATTERN = re.compile(
    r"(?:ÖNORM|OENORM|DIN)?\s*"
    r"(?P<series>EN|B)\s+(?P<number>\d{3,5}(?:-\d{1,2})*)"
    r"(?::\d{4}(?:-\d{2})?(?:-\d{2})?)?"  # optional edition, ":2015" / ":2011-12"
    r"\s*,?\s*(?:Abschnitt|Absatz|Kapitel|§)\s*"
    r"(?P<clause>\d+(?:\.\d+)+)"
)


# German national annexes state their determinations differently, and never
# name the norm: "NDP zu 6.2.3(2)" (nationally determined parameter) and
# "NCI zu 6.2.3" (non-contradictory complementary information). Measured on
# the DIN corpus: 1,487 occurrences across 51 documents, of which exactly one
# also names the norm. The Austrian form — "Festlegung zu ÖNORM EN 1992-1-1,
# Abschnitt 3.1.6(1)P" — names it every time, which is what the pattern above
# was built for, and why enrichment resolved 4 chunks out of 21,909 German
# ones against 565 out of 10,511 Austrian.
#
# A bare reference is still not resolvable in general — several documents in
# a project share clause numbers — but inside a national annex it is: the
# annex modifies its own parent, and its designation says which that is.
# DIN EN 1991-1-1/NA addresses DIN EN 1991-1-1 and nothing else.
NA_CLAUSE_PATTERN = re.compile(
    r"\b(?:NDP|NCI)\s+zu\s+(?:Abschnitt\s*)?(?P<clause>\d+(?:\.\d+)+)"
)

# The parent of a national annex, read off its own designation. Annex-letter
# clauses ("NDP zu A2.3.1", 57 of the 1,487) are deliberately not matched
# above: chunk headings are digits-only, so such a clause has nothing to
# resolve against and would only produce log noise.
_NATIONAL_ANNEX = re.compile(
    r"(?:DIN|ÖNORM|OENORM)?\s*(?P<series>EN|B)\s+(?P<number>\d{3,5}(?:-\d{1,2})*)\s*/\s*NA"
)


def _annex_parent(norm_reference: str | None) -> tuple[str, str] | None:
    """(series, number) of the norm a national annex modifies, or None."""
    if not norm_reference:
        return None
    match = _NATIONAL_ANNEX.search(normalize_reference_text(norm_reference))
    return (match.group("series"), match.group("number")) if match else None


@dataclass(frozen=True)
class ClauseReference:
    series: str
    number: str
    clause: str

    @property
    def designation(self) -> str:
        return f"{self.series} {self.number}"


def extract_clause_references(
    text: str, owner_reference: str | None = None
) -> list[ClauseReference]:
    """Every (norm, clause) pair the text addresses by number, in order.

    References that name their norm are extracted from any document. A bare
    "Abschnitt 6.2.3" is not: several documents in a project share clause
    numbers, so it cannot be resolved deterministically.

    The exception is a national annex, which is what `owner_reference`
    supplies. An annex modifies its own parent and nothing else, so the
    German "NDP zu 6.2.3" and "NCI zu 6.2.3" resolve against the norm named
    in the annex's own designation. Called without an owner, behaviour is
    unchanged.
    """
    flat = normalize_reference_text(text)
    references: list[ClauseReference] = []
    seen: set[ClauseReference] = set()

    def add(series: str, number: str, clause: str) -> None:
        reference = ClauseReference(series=series, number=number, clause=clause)
        if reference not in seen:
            seen.add(reference)
            references.append(reference)

    for match in CLAUSE_REFERENCE_PATTERN.finditer(flat):
        add(match.group("series"), match.group("number"), match.group("clause"))

    parent = _annex_parent(owner_reference)
    if parent:
        for match in NA_CLAUSE_PATTERN.finditer(flat):
            add(parent[0], parent[1], match.group("clause"))

    return references


def _reference_matches_document(reference: ClauseReference, norm_reference: str | None) -> bool:
    """Whether a stored document *is* the referenced norm.

    The full designation must match, not just the number: clause numbers only
    mean something inside one norm, so EN 1992-1-1 must not resolve against
    B 1991-1-3 (different family) or B 1992-1-1 (the annex, a different
    document in the same family — docs/norm-graph.md records that B 1992-2
    links to both EN 1992-2 and EN 1992-1-1, so pairing by number alone is
    insufficient). The character after the number is checked so EN 1992-1
    does not match inside EN 1992-1-1 and EN 1990 does not match the
    distinct document DIN EN 1990/NA.
    """
    if not norm_reference:
        return False
    flat = normalize_reference_text(norm_reference)
    target = reference.designation
    for match in re.finditer(re.escape(target), flat):
        before = flat[match.start() - 1] if match.start() > 0 else " "
        after = flat[match.end()] if match.end() < len(flat) else " "
        if not before.isalnum() and after not in "0123456789-/.":
            return True
    return False


# Mirrors the heading the chunker re-attaches to every piece of a clause
# (chunk_pages in services/chunking.py): the first line of a chunk is the
# heading line of that clause. A heading with no letters carries no
# vocabulary worth appending.
_HEADING_LINE = re.compile(r"^(\d+(?:\.\d+)+)\s+\S")


def _clause_heading(chunk_text: str) -> tuple[str, str] | None:
    first_line = chunk_text.lstrip().split("\n", 1)[0].strip()
    match = _HEADING_LINE.match(first_line)
    if not match or not any(ch.isalpha() for ch in first_line):
        return None
    return match.group(1), first_line


def _log_unresolved(
    reference: ClauseReference, document_id: str, why: str, logged: set[tuple[str, str]]
) -> None:
    key = (reference.designation, reference.clause)
    if key in logged:
        return
    logged.add(key)
    logger.warning(
        "Unresolved norm reference %s Abschnitt %s cited in document %s (%s); "
        "chunk left unenriched",
        reference.designation,
        reference.clause,
        document_id,
        why,
    )


def enrich_project_references(project_id: str) -> int:
    """Re-resolves clause references across the whole project.

    Returns the number of chunks whose indexed text changed. Deterministic
    and idempotent: enrichment is always recomputed from the original chunk
    text, so re-running never appends twice, and a reference that becomes
    resolvable once its parent document arrives is picked up on the next
    pass regardless of upload order. No LLM is involved at any point.

    An unresolvable reference — the named norm is not in the project (e.g.
    the published typo ÖNORM EN 1933-1-1 in B 1993-1-1), or it is but the
    clause has no heading there — leaves the chunk unenriched and is logged,
    never rewritten and never silently dropped.
    """
    collection = get_collection(project_id)
    data = collection.get(include=["documents", "metadatas"])
    ids = data["ids"]
    if not ids:
        return 0
    stored_texts = data["documents"]
    metadatas = data["metadatas"]

    # Original text per chunk: collections indexed before this feature have
    # no raw_text, and their stored document text is by definition original.
    raw_texts = [
        meta.get("raw_text") or stored
        for stored, meta in zip(stored_texts, metadatas)
    ]

    # Clause heading map per document, built from original text so headings
    # are never read out of previously appended enrichment.
    document_norm_refs: dict[str, str] = {}
    headings: dict[str, dict[str, str]] = {}
    for meta, raw in zip(metadatas, raw_texts):
        document_id = meta["document_id"]
        document_norm_refs.setdefault(document_id, meta.get("norm_reference") or "")
        found = _clause_heading(raw)
        if found:
            headings.setdefault(document_id, {}).setdefault(found[0], found[1])

    changed_ids: list[str] = []
    changed_texts: list[str] = []
    changed_metas: list[dict] = []
    logged: set[tuple[str, str]] = set()

    for chunk_id, stored, meta, raw in zip(ids, stored_texts, metadatas, raw_texts):
        own_document_id = meta["document_id"]
        additions: list[str] = []
        for reference in extract_clause_references(
            raw, document_norm_refs.get(own_document_id)
        ):
            matching = [
                document_id
                for document_id, norm_ref in document_norm_refs.items()
                if _reference_matches_document(reference, norm_ref)
            ]
            # A norm cites its own clauses constantly; enriching a chunk
            # with headings from its own document adds nothing.
            others = [d for d in matching if d != own_document_id]
            if not others:
                if not matching:
                    _log_unresolved(reference, own_document_id, "not in this project", logged)
                continue
            heading = None
            for document_id in others:
                candidate = headings.get(document_id, {}).get(reference.clause)
                if candidate:
                    heading = candidate
                    break
            if heading is None:
                _log_unresolved(reference, own_document_id, "clause heading not found", logged)
                continue
            if heading not in additions:
                additions.append(heading)

        enriched = raw + "\n" + "\n".join(additions) if additions else raw
        if enriched == stored:
            continue
        new_meta = dict(meta)
        new_meta["raw_text"] = raw
        changed_ids.append(chunk_id)
        changed_texts.append(enriched)
        changed_metas.append(new_meta)

    if changed_ids:
        vectors = get_embeddings().embed_documents(changed_texts)
        collection.update(
            ids=changed_ids,
            embeddings=vectors,
            documents=changed_texts,
            metadatas=changed_metas,
        )
    return len(changed_ids)
