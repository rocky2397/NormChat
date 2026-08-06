# Eval run — 2026-08-06, surfacing conflicting norm parts

> **Note:** scored against the rubric as it stood at the time. See `eval/runs/README.md` for the re-scoring against the current, stricter grading in `eval/questions.md`.


Follows `2026-08-06-compound-expansion.md`. Same index; answer-behaviour
change only, no retrieval change.

## The problem this addresses

`EN 1992-1-1` recommends α_cc = 1,0; `EN 1992-2` recommends 0,85. Both are
correct in their own scope — buildings and bridges. With both in context and
nothing establishing which governs, Q5's answer flipped between runs on
context ordering alone: correct in run 5, wrong in run 6, with **identical
national-annex evidence** in both.

Picking a value was never going to be reliable, so the tool now contrasts
them instead.

## Change

Deterministic detection plus a presentation rule, rather than a prompt rule
alone — the earlier `[Quelle N]` leak showed that instructions on their own
do not hold.

- `_parts_in_conflict()` groups the retrieved sources by norm family and
  flags any family where more than one **part** appears. A European norm and
  its national annex share a part (`EN 1992-1-1` and `B 1992-1-1` are both
  `1992-1-1`), so they are correctly *not* treated as a conflict — they are
  meant to be read together.
- When a conflict is found, the specific collision is named in the user
  message, and a `SYSTEM_PROMPT` rule requires attributing each value to its
  part and stating the applicable scope rather than choosing.

## Result: Q5 answers the way the product promises

> In der ÖNORM EN 1992-1-1 … Der empfohlene Wert für α_cc ist 1,0 …
>
> In der ÖNORM EN 1992-2 … jedoch mit einem empfohlenen Wert von 0,85 …
>
> Für Österreich … ÖNORM B 1992-1-1 … übernimmt den empfohlenen Wert aus der
> ÖNORM EN 1992-1-1, Abschnitt 3.1.6(1)P … der Wert 1,0 …
>
> Zusammenfassend:
> - ÖNORM EN 1992-1-1: 1,0
> - ÖNORM EN 1992-2: 0,85
> - ÖNORM B 1992-1-1 (nationale Ergänzung): übernimmt 1,0

Both values are present, each attributed to its part, and the Austrian
national decision is stated. Nothing is silently chosen, and the engineer
can see exactly what governs what.

No regressions: Q1–Q4 unchanged, all EN clause targets still hit, no citation
labels leaked.

## Remaining gap

The answer attributes the values to their parts but does not say that
`EN 1992-2` is the **bridge** part — the retrieved chunk does not state its
own scope, and the prompt forbids filling that in from general knowledge.
The contrast is therefore visible but its significance is left to the reader.
Carrying each document's title through ingestion would close this; the title
is on the cover page, which `services/norm_identity.py` already parses.

The `B 1992-1-1` national content still arrives via the overview table on
page 6 rather than clause §6.1.4 on page 12. Same statement, less precise
citation.
