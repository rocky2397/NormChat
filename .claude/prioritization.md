# Prioritization Policy for NormChat

NormChat is a RAG-powered chat app for construction professionals in the
DACH region: users upload norm PDFs (DIN, LBO, Eurocode, ÖNORM) and query
them with cited source passages and in-PDF highlighting.

## Ranking criteria, in order
1. Bugs that break core flows: PDF upload/ingestion, chat answers,
   citation/highlighting accuracy (label: bug)
2. Tickets blocking other tickets (referenced by "blocked by" in bodies)
3. Small, well-specified features with clear acceptance criteria
4. Tech debt with a measurable payoff stated in the ticket
5. Everything else

## Hard rules
- Never pick a ticket without acceptance criteria. Classify as blocked
  and ask for them.
- Never pick tickets labeled "discuss", "design", or "wontfix".
- Never pick tickets touching authentication, billing/payments, or
  database schema migrations. These require human implementation.
  Classify as deprioritized with reason "requires human owner".
- Never pick tickets that change RAG retrieval quality or embedding
  strategy without an evaluation method stated in the ticket — wrong
  citations in a norms tool are worse than no answer. Classify as
  blocked and ask how correctness will be verified.
- Prefer tickets estimated ≤ 1 day (label: size/S or size/M).
- Max one ticket in flight at a time (WIP limit enforced by workflow).

## Definition of "not worth working on"
- Stale (no update in 60 days) and no priority label → deprioritize.
- Duplicate of an open PR or issue → deprioritize with link.
- Vague one-liners → blocked, ask a concrete clarifying question.
