"""Per-question retrieval trace: where each *expected* source ranked at
every pipeline stage, and whether it ended up grounded in the answer.

`backend/eval/retrieval_probe.py` already reports per-stage rank for gold
(norm_reference, page) labels, but only for retrieval — it never calls
generate_answer() or the excerpt-grounding step, so it cannot say whether a
source that reached the final context actually produced a `highlight_snippet`
the answer relied on. This module runs the full chat() pipeline once per
question and adds that: which of the *expected* sources were present after
each stage, at what rank, and whether the sources that made it into context
were grounded — the "unused-context" signal the end-to-end grade cannot see.

Expected sources are (norm_reference, page, clause) triples, resolved to
chunk ids against the live corpus at run time. Chroma ids are
`{document_id}_{chunk_index}` and change on every re-ingest, so pinning a
label to one would make it stale the moment the corpus is rebuilt — see the
`trace-gold` blocks in eval/questions.md. Resolving a triple that matches no
chunk raises rather than reporting a silent miss, because those are two
different failures: "the pipeline did not surface it" is a retrieval defect,
"no such chunk exists" is a wrong label or an incomplete corpus, and
conflating them would make the trace's own recall numbers misleading.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from services.llm import PIPELINE_STAGES, RetrievalTrace, chat
from services.norm_identity import normalize_reference_text
from services.storage import get_collection

REPO_ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_FILE = REPO_ROOT / "eval" / "questions.md"

# The stages a trace-gold label is checked against. Named for what they are
# in eval/questions.md's own vocabulary (vector query, BM25 ranking, RRF
# fusion, cross-encoder rerank, clause lookup) rather than restated as a
# fixed tuple, so a stage added to the pipeline appears here too.
TRACE_STAGES = tuple(s for s in PIPELINE_STAGES if s != "deltas_admitted")

RECALL_CUTOFFS = (10, 100)


class UnresolvedExpectedSourceError(Exception):
    """An expected source's (norm_reference, page[, clause]) matches no
    chunk anywhere in the project's corpus.

    Raised instead of letting the source silently score a miss at every
    stage: that would be indistinguishable from a real retrieval failure,
    when the actual defect is a wrong page/clause in eval/questions.md or a
    corpus that is missing a document the question set assumes is loaded.
    """


@dataclass(frozen=True)
class ExpectedSource:
    """One line of a `trace-gold` block.

    `clause` is None for a label that only pins a page — a table or figure
    has no single clause number to search for (Q6, Q7 in
    eval/questions.md), and a document-level label uses `page=None` the same
    way the `gold` block's `*` does.
    """

    norm_reference: str
    page: int | None
    clause: str | None


@dataclass
class ExpectedSourceTrace:
    expected: ExpectedSource
    chunk_ids: tuple[str, ...]  # resolved against the full corpus
    stage_ranks: dict[str, int | None]
    grounded: bool | None  # None when the source never reached the final context


@dataclass
class ContextSourceTrace:
    """One source that made it into the answer's context, whether or not it
    was one of the expected sources."""

    norm_reference: str | None
    page_number: int
    grounded: bool


@dataclass
class QuestionTrace:
    number: int
    text: str
    project_id: str
    expected: list[ExpectedSourceTrace] = field(default_factory=list)
    context: list[ContextSourceTrace] = field(default_factory=list)


_TRACE_GOLD_BLOCK = re.compile(r"^```trace-gold\s*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_QUESTION_HEADING = re.compile(r"^## Q(\d+)\s*$", re.MULTILINE)


def _question_text(section: str) -> str:
    lines: list[str] = []
    for line in section.splitlines():
        if line.startswith(">"):
            lines.append(line.lstrip(">").strip())
        elif lines:
            break
    return " ".join(lines).strip()


def parse_expected_sources(section: str) -> tuple[ExpectedSource, ...]:
    """Every line of a section's `trace-gold` block, or `()` if it has none.

    Format: `norm_reference: page[: clause]`, with `page` either an int or
    `*` for a document-level label (mirrors the `gold` block's convention).
    """
    match = _TRACE_GOLD_BLOCK.search(section)
    if not match:
        return ()
    sources: list[ExpectedSource] = []
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(":")]
        if len(parts) not in (2, 3) or not parts[1]:
            raise ValueError(
                "Malformed trace-gold line "
                f"(want 'norm_reference: page[: clause]'): {raw!r}"
            )
        reference = normalize_reference_text(parts[0])
        page = None if parts[1] == "*" else int(parts[1])
        clause = parts[2] if len(parts) == 3 and parts[2] else None
        sources.append(ExpectedSource(norm_reference=reference, page=page, clause=clause))
    return tuple(sources)


@dataclass(frozen=True)
class QuestionSpec:
    number: int
    text: str
    expected: tuple[ExpectedSource, ...]


def parse_questions(markdown: str) -> list[QuestionSpec]:
    """Every `## Qn` section with a non-empty `trace-gold` block.

    Sections without one (Q1–Q7 as originally proposed, before an engineer
    signs off a clause number) are simply absent from the result, the same
    way a `TBD` gold block is skipped by retrieval_probe.py.
    """
    headings = list(_QUESTION_HEADING.finditer(markdown))
    questions: list[QuestionSpec] = []
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown)
        section = markdown[heading.end():end]
        expected = parse_expected_sources(section)
        if not expected:
            continue
        questions.append(
            QuestionSpec(
                number=int(heading.group(1)),
                text=_question_text(section),
                expected=expected,
            )
        )
    return questions


def _load_corpus(project_id: str) -> tuple[dict[str, dict], dict[str, str]]:
    """(id -> metadata, id -> text used for clause matching) for every chunk
    ever ingested into the project — the resolver must see the whole
    corpus, not just what one query happened to retrieve."""
    collection = get_collection(project_id)
    chunks = collection.get(include=["documents", "metadatas"])
    ids = chunks["ids"]
    id_to_meta = dict(zip(ids, chunks["metadatas"]))
    id_to_text = {
        cid: (meta.get("raw_text") or doc)
        for cid, meta, doc in zip(ids, chunks["metadatas"], chunks["documents"])
    }
    return id_to_meta, id_to_text


def _clause_pattern(clause: str) -> re.Pattern:
    # Bounded on both sides so "6.2" does not match inside "16.2" or "6.20"
    # — the same rule services/llm.py's clause lookup applies.
    return re.compile(rf"(?<![\d.]){re.escape(clause)}(?![\d])")


def _matches(meta: dict, text: str, expected: ExpectedSource) -> bool:
    reference = normalize_reference_text(meta.get("norm_reference") or "")
    if reference != expected.norm_reference:
        return False
    if expected.page is not None:
        try:
            if int(meta["page_number"]) != expected.page:
                return False
        except (KeyError, TypeError, ValueError):
            return False
    if expected.clause is not None and not _clause_pattern(expected.clause).search(text):
        return False
    return True


def resolve_expected_source(
    expected: ExpectedSource, id_to_meta: dict[str, dict], id_to_text: dict[str, str]
) -> tuple[str, ...]:
    """Chunk ids in the corpus matching `expected`, or raises if none do."""
    matches = tuple(
        cid for cid in id_to_meta if _matches(id_to_meta[cid], id_to_text[cid], expected)
    )
    if not matches:
        clause_part = f", clause {expected.clause}" if expected.clause else ""
        page_part = "any page" if expected.page is None else f"page {expected.page}"
        raise UnresolvedExpectedSourceError(
            f"No chunk matches expected source {expected.norm_reference!r} "
            f"({page_part}{clause_part}). Check eval/questions.md against the "
            "ingested corpus — this is a labelling or corpus problem, not a "
            "retrieval result."
        )
    return matches


def _best_rank(chunk_ids: tuple[str, ...], stage_ids: list[str]) -> int | None:
    positions = [stage_ids.index(cid) + 1 for cid in chunk_ids if cid in stage_ids]
    return min(positions) if positions else None


def run_question_trace(project_id: str, spec: QuestionSpec) -> QuestionTrace:
    """Runs the full chat() pipeline once and builds the trace from it.

    One chat completion and one excerpt-grounding call happen here (inside
    chat()), in addition to the query embedding retrieve_sources() makes —
    this is not the retrieval-only probe in backend/eval/retrieval_probe.py.
    """
    id_to_meta, id_to_text = _load_corpus(project_id)
    resolved = [
        (expected, resolve_expected_source(expected, id_to_meta, id_to_text))
        for expected in spec.expected
    ]

    trace = RetrievalTrace()
    response = chat(project_id, spec.text, trace=trace)

    grounded_pages = {
        (source.norm_reference, source.page_number)
        for source in response.sources
        if source.highlight_snippet
    }
    context_pages = {(source.norm_reference, source.page_number) for source in response.sources}

    expected_traces = []
    for expected, chunk_ids in resolved:
        stage_ranks = {
            stage: _best_rank(chunk_ids, trace.ids(stage)) for stage in TRACE_STAGES
        }
        matched_pages = {
            (id_to_meta[cid].get("norm_reference"), int(id_to_meta[cid]["page_number"]))
            for cid in chunk_ids
        }
        if matched_pages & context_pages:
            grounded = bool(matched_pages & grounded_pages)
        else:
            grounded = None
        expected_traces.append(
            ExpectedSourceTrace(
                expected=expected,
                chunk_ids=chunk_ids,
                stage_ranks=stage_ranks,
                grounded=grounded,
            )
        )

    context_traces = [
        ContextSourceTrace(
            norm_reference=source.norm_reference,
            page_number=source.page_number,
            grounded=bool(source.highlight_snippet),
        )
        for source in response.sources
    ]

    return QuestionTrace(
        number=spec.number,
        text=spec.text,
        project_id=project_id,
        expected=expected_traces,
        context=context_traces,
    )


def recall_at(traces: list[ExpectedSourceTrace], stage: str, k: int) -> tuple[int, int]:
    """(hit, total) expected sources ranked at or above `k` at `stage`."""
    hits = 0
    for t in traces:
        rank = t.stage_ranks[stage]
        if rank is not None and rank <= k:
            hits += 1
    return hits, len(traces)


def unused_context_rate(context: list[ContextSourceTrace]) -> tuple[int, int]:
    """(sources without a grounded highlight, total sources) placed in the
    final answer context — the sources that reached the model but produced
    no located, verbatim excerpt it demonstrably relied on."""
    if not context:
        return 0, 0
    ungrounded = sum(1 for c in context if not c.grounded)
    return ungrounded, len(context)


def _format_rank(rank: int | None) -> str:
    return "miss" if rank is None else str(rank)


def _format_grounded(grounded: bool | None) -> str:
    if grounded is None:
        return "not reached"
    return "yes" if grounded else "no"


def _format_recall(hits: int, total: int) -> str:
    if total == 0:
        return "—"
    return f"{hits}/{total} ({hits / total:.2f})"


def render_question_trace(trace: QuestionTrace, date_str: str) -> str:
    lines = [
        f"# Retrieval trace — Q{trace.number} — {date_str}",
        "",
        f"> {trace.text}",
        "",
        f"Project `{trace.project_id}`. Full pipeline run (retrieval and answer "
        "generation) — one chat completion and one excerpt-grounding call were "
        "made in addition to the query embedding, so this is not a headless "
        "retrieval-only probe.",
        "",
        "## Expected sources",
        "",
        "Rank is 1-based at each stage, or `miss`. `grounded` is `yes` when a "
        "chunk matching this source reached the final context and its "
        "`highlight_snippet` was found; `not reached` when no matching chunk "
        "reached the final context at all.",
        "",
        "| norm_reference | page | clause | " + " | ".join(TRACE_STAGES) + " | grounded |",
        "| --- | --- | --- | " + " | ".join("---" for _ in TRACE_STAGES) + " | --- |",
    ]
    for t in trace.expected:
        cells = " | ".join(_format_rank(t.stage_ranks[stage]) for stage in TRACE_STAGES)
        page = "any" if t.expected.page is None else str(t.expected.page)
        clause = t.expected.clause or "—"
        lines.append(
            f"| `{t.expected.norm_reference}` | {page} | {clause} | {cells} "
            f"| {_format_grounded(t.grounded)} |"
        )

    lines += [
        "",
        "### Recall over the expected set",
        "",
        "| stage | " + " | ".join(f"recall@{k}" for k in RECALL_CUTOFFS) + " |",
        "| --- | " + " | ".join("---" for _ in RECALL_CUTOFFS) + " |",
    ]
    for stage in TRACE_STAGES:
        cells = " | ".join(
            _format_recall(*recall_at(trace.expected, stage, k)) for k in RECALL_CUTOFFS
        )
        lines.append(f"| {stage} | {cells} |")

    lines += [
        "",
        "## Context sources and grounding",
        "",
        "Every source placed in the final answer context, whether or not it "
        "was one of the expected sources above — this is what the "
        "unused-context rate is computed from.",
        "",
        "| # | norm_reference | page | grounded |",
        "| --- | --- | --- | --- |",
    ]
    for i, c in enumerate(trace.context, start=1):
        lines.append(f"| {i} | `{c.norm_reference}` | {c.page_number} | {'yes' if c.grounded else 'no'} |")

    ungrounded, total = unused_context_rate(trace.context)
    lines += [
        "",
        f"Unused-context rate: {_format_recall(ungrounded, total)} — context "
        "sources whose highlight_snippet did not ground.",
        "",
    ]
    return "\n".join(lines)
