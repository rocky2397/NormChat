"""Per-stage retrieval probe against the gold labels in eval/questions.md.

Runs retrieval only — no answer generation and no OpenAI chat completion
call (the query-embedding call is the only model use) — for every reference
question that has gold labels, and reports where the expected chunks rank at
each stage of the pipeline:

    dense -> lexical -> fused -> reranked -> final

An end-to-end grade cannot distinguish "the chunk never entered the
candidate pool" from "the reranker dropped it" from "it was in context and
the answer ignored it"; this table can, for the first two.

Gold labels are (norm_reference, page_number) pairs, never chunk ids:
Chroma ids are {document_id}_{chunk_index} with a per-ingestion document_id,
so they do not survive a re-ingest, while the norm reference and PDF page
index are stable properties of the corpus.

Usage, from backend/:

    python -m eval.retrieval_probe --project <project-id>

The report is printed and written under eval/runs/, so probe runs sit next
to the graded run notes.
"""

import argparse
import datetime
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from services.llm import RetrievalTrace, retrieve_sources
from services.norm_identity import normalize_reference_text

REPO_ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_FILE = REPO_ROOT / "eval" / "questions.md"
RUNS_DIR = REPO_ROOT / "eval" / "runs"

# (report column, RetrievalTrace attribute), in pipeline order.
STAGES = (
    ("dense", "vector_ids"),
    ("lexical", "bm25_ids"),
    ("fused", "fused_ids"),
    ("reranked", "reranked_ids"),
    ("final", "final_ids"),
)


@dataclass(frozen=True)
class GoldLabel:
    """One expected source: a norm and the PDF pages its clause spans."""

    norm_reference: str
    pages: frozenset[int]


@dataclass(frozen=True)
class ProbeQuestion:
    number: int
    text: str
    gold: tuple[GoldLabel, ...]


@dataclass
class GoldResult:
    gold: GoldLabel
    ranks: dict[str, int | None]


@dataclass
class QuestionResult:
    question: ProbeQuestion
    rows: list[GoldResult]


_QUESTION_HEADING = re.compile(r"^## Q(\d+)\s*$", re.MULTILINE)
_GOLD_BLOCK = re.compile(r"^```gold\s*\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _question_text(section: str) -> str:
    """The question itself: the first blockquote in the section."""
    lines: list[str] = []
    for line in section.splitlines():
        if line.startswith(">"):
            lines.append(line.lstrip(">").strip())
        elif lines:
            break
    return " ".join(lines).strip()


def _parse_gold_block(section: str) -> tuple[GoldLabel, ...]:
    match = _GOLD_BLOCK.search(section)
    if not match:
        return ()
    labels: list[GoldLabel] = []
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if not line or line.upper() == "TBD" or line.startswith("#"):
            continue
        reference, sep, pages = line.partition(":")
        if not sep or not pages.strip():
            raise ValueError(
                f"Malformed gold line (want 'norm_reference: page[, page...]'): {raw!r}"
            )
        labels.append(
            GoldLabel(
                norm_reference=normalize_reference_text(reference),
                pages=frozenset(int(p) for p in pages.split(",")),
            )
        )
    return tuple(labels)


def parse_questions(markdown: str) -> list[ProbeQuestion]:
    """Every `## Qn` section, with its gold labels — an empty tuple when the
    gold block is missing or still TBD, so callers can report those as
    skipped rather than silently dropping them."""
    headings = list(_QUESTION_HEADING.finditer(markdown))
    questions: list[ProbeQuestion] = []
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown)
        section = markdown[heading.end():end]
        questions.append(
            ProbeQuestion(
                number=int(heading.group(1)),
                text=_question_text(section),
                gold=_parse_gold_block(section),
            )
        )
    return questions


def chunk_matches_gold(meta: dict, gold: GoldLabel) -> bool:
    """A hit is the right page of the right document.

    The norm reference must match exactly (after typographic normalization)
    so that `EN 1992-1-1` p. 21 never satisfies a gold label for
    `B 1992-1-1` p. 21 — the EN and its national annex share clause
    numbering and vocabulary, and conflating them is the failure mode the
    question set exists to catch.
    """
    reference = normalize_reference_text(meta.get("norm_reference") or "")
    if reference != gold.norm_reference:
        return False
    try:
        page = int(meta["page_number"])
    except (KeyError, TypeError, ValueError):
        return False
    return page in gold.pages


def first_gold_rank(ids: list[str], id_to_meta: dict, gold: GoldLabel) -> int | None:
    """1-based rank of the first chunk matching the gold label, or None."""
    for rank, chunk_id in enumerate(ids, start=1):
        if chunk_matches_gold(id_to_meta.get(chunk_id, {}), gold):
            return rank
    return None


def probe_question(project_id: str, question: ProbeQuestion) -> QuestionResult:
    trace = RetrievalTrace()
    retrieve_sources(project_id, question.text, trace=trace)
    rows = [
        GoldResult(
            gold=gold,
            ranks={
                stage: first_gold_rank(getattr(trace, attr), trace.id_to_meta, gold)
                for stage, attr in STAGES
            },
        )
        for gold in question.gold
    ]
    return QuestionResult(question=question, rows=rows)


def recall_at(results: list[QuestionResult], stage: str, k: int) -> tuple[int, int]:
    """(hit gold labels, total gold labels) at rank <= k for one stage."""
    hits = total = 0
    for question_result in results:
        for row in question_result.rows:
            total += 1
            rank = row.ranks[stage]
            if rank is not None and rank <= k:
                hits += 1
    return hits, total


def _format_rank(rank: int | None) -> str:
    return "miss" if rank is None else str(rank)


def _format_recall(hits: int, total: int) -> str:
    if total == 0:
        return "—"
    return f"{hits}/{total} ({hits / total:.2f})"


def render_report(
    project_id: str,
    results: list[QuestionResult],
    skipped: list[int],
    date_str: str,
) -> str:
    lines = [
        f"# Retrieval probe — {date_str}",
        "",
        "Headless retrieval-only run (`python -m eval.retrieval_probe`) against",
        f"project `{project_id}`. No answer was generated and no chat completion",
        "was called; the query embedding is the only model call. Gold labels come",
        "from the `gold` blocks in `eval/questions.md`, and a chunk counts as a",
        "hit when its `norm_reference` and `page_number` metadata match one.",
        "",
        "Each cell is the 1-based rank of the first matching chunk at that",
        "stage, or `miss`. Stages are in pipeline order; `reranked` and `final`",
        "are cut to context size, so a `miss` there with a hit upstream",
        "localizes where the chunk was lost.",
        "",
        "| question | gold | " + " | ".join(stage for stage, _ in STAGES) + " |",
        "| --- | --- | " + " | ".join("---" for _ in STAGES) + " |",
    ]
    for question_result in results:
        for row in question_result.rows:
            pages = ", ".join(str(p) for p in sorted(row.gold.pages))
            cells = " | ".join(_format_rank(row.ranks[stage]) for stage, _ in STAGES)
            lines.append(
                f"| Q{question_result.question.number} "
                f"| `{row.gold.norm_reference}` p. {pages} | {cells} |"
            )
    lines += [
        "",
        "## Recall across the question set",
        "",
        "Fraction of gold labels ranked at or above the cutoff, per stage.",
        "",
        "| stage | recall@10 | recall@100 |",
        "| --- | --- | --- |",
    ]
    for stage, _ in STAGES:
        lines.append(
            f"| {stage} | {_format_recall(*recall_at(results, stage, 10))} "
            f"| {_format_recall(*recall_at(results, stage, 100))} |"
        )
    if skipped:
        lines += [
            "",
            "Skipped (gold labels still TBD in `eval/questions.md`): "
            + ", ".join(f"Q{n}" for n in skipped)
            + ".",
        ]
    lines.append("")
    return "\n".join(lines)


def _default_output_path(date_str: str) -> Path:
    path = RUNS_DIR / f"{date_str}-retrieval-probe.md"
    counter = 2
    while path.exists():
        path = RUNS_DIR / f"{date_str}-retrieval-probe-{counter}.md"
        counter += 1
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Report where the gold chunks rank at each retrieval stage."
    )
    parser.add_argument("--project", required=True, help="project id to probe")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="report path (default: eval/runs/<date>-retrieval-probe.md)",
    )
    args = parser.parse_args(argv)

    questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8"))
    probed = [q for q in questions if q.gold]
    skipped = [q.number for q in questions if not q.gold]
    if not probed:
        sys.exit(f"No question in {QUESTIONS_FILE} has gold labels.")

    results: list[QuestionResult] = []
    for question in probed:
        print(f"Probing Q{question.number} ...", file=sys.stderr)
        results.append(probe_question(args.project, question))

    if all(rank is None for r in results for row in r.rows for rank in row.ranks.values()):
        print(
            "Warning: no gold label matched at any stage. If every row is a "
            "miss, check that the project id is right and ingestion finished.",
            file=sys.stderr,
        )

    date_str = datetime.date.today().isoformat()
    report = render_report(args.project, results, skipped, date_str)
    output = args.output or _default_output_path(date_str)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report written to {output}", file=sys.stderr)


if __name__ == "__main__":
    main()
