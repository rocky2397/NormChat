"""Per-question retrieval trace, run against a live project.

Runs the full chat() pipeline — retrieval, answer generation and excerpt
grounding — once per question that carries a `trace-gold` block in
eval/questions.md, and writes one trace file per question under
eval/traces/. Unlike eval/retrieval_probe.py this calls the model: one chat
completion and one grounding call per question, in addition to the query
embedding.

Usage, from backend/:

    python -m eval.retrieval_trace_cli --project <project-id>

A `trace-gold` label that matches no chunk anywhere in the project's corpus
stops the run with an error (services.retrieval_trace.
UnresolvedExpectedSourceError) rather than writing a trace that silently
scores it a miss — see that module's docstring for why the two are not the
same failure.
"""

import argparse
import datetime
import sys
from pathlib import Path

from services.retrieval_trace import (
    QUESTIONS_FILE,
    REPO_ROOT,
    UnresolvedExpectedSourceError,
    parse_questions,
    render_question_trace,
    run_question_trace,
)

TRACES_DIR = REPO_ROOT / "eval" / "traces"


def _output_path(number: int, date_str: str) -> Path:
    return TRACES_DIR / f"Q{number}-{date_str}.md"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Write a per-question retrieval trace for every question "
        "in eval/questions.md that carries a trace-gold block."
    )
    parser.add_argument("--project", required=True, help="project id to trace")
    args = parser.parse_args(argv)

    questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8"))
    if not questions:
        sys.exit(f"No question in {QUESTIONS_FILE} carries a trace-gold block.")

    date_str = datetime.date.today().isoformat()
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for spec in questions:
        print(f"Tracing Q{spec.number} ...", file=sys.stderr)
        try:
            trace = run_question_trace(args.project, spec)
        except UnresolvedExpectedSourceError as exc:
            sys.exit(f"Q{spec.number}: {exc}")
        report = render_question_trace(trace, date_str)
        output = _output_path(spec.number, date_str)
        output.write_text(report, encoding="utf-8")
        written.append(output)
        print(report, file=sys.stderr)

    print(f"Wrote {len(written)} trace file(s):", file=sys.stderr)
    for path in written:
        print(f"  {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
