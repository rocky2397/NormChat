# Run history, re-scored against the current rubric

The grading in `eval/questions.md` was tightened after the runs below were
recorded. The original files kept their contemporaneous scores; this table
re-scores every run against the current rubric so the trend is comparable.

Two rules did the re-scoring work:

- **Front matter does not satisfy the national-annex check.** Citing
  `ÖNORM B 1992-1-1, S. 4` (the Vorwort) is not citing the annex.
- **An unsourced claim is `schlecht`, not `mittel`.** Asserting that national
  provisions apply without citing one is worse than admitting they were not
  found, because the reader cannot check it.

Both changes make the earlier runs look worse than originally recorded. That
is the point — the old scores were flattered by a loophole.

| run | Q1 | Q2 | Q3 | Q4 | Q5 |
| --- | --- | --- | --- | --- | --- |
| 1 baseline | gut · *leak* | mittel | **schlecht** | **schlecht** | **schlecht** |
| 2 cover+TOC+foreword | **schlecht** | mittel | **schlecht** | **schlecht** | **schlecht** |
| 3 cover+TOC only | gut | mittel | **schlecht** | **schlecht** | **schlecht** |
| 5 clause lookup | gut | mittel | **schlecht** | **schlecht** | gut |
| 6 +compound +family | gut | mittel | mittel | **schlecht** | **schlecht** |
| 7 part conflict | gut | mittel | mittel | **schlecht** | gut |
| 8 current | gut | mittel | **schlecht** | mittel | gut |

## What changed against the originally recorded scores

**Run 1 Q3, Q4 → `schlecht`** (were recorded `schlecht` already, for a
different reason). Originally marked down for missing the clause; under the
current rubric they also fail the annex check, since every `B 1992-1-1`
source was front matter.

**Run 2 Q1 → `schlecht`** (was recorded as a regression but not graded).
*"ÖNORM B 1995-1-2: Diese Norm ist die konsolidierte Fassung von ÖNORM
EN 1995-1-2"* is a factual error — that phrase describes the EN document.
Wrong beats incomplete.

**Runs 5 and 7 Q3 → `schlecht`.** These were not individually graded at the
time. Both name national provisions while citing only front matter.

**Run 6 Q5 → `schlecht`.** Recorded as "regressed"; the rubric makes it
explicit — it answered 0,85 from `ÖNORM EN 1992-2`, the bridge part, for a
question about a beam.

**Run 8 Q3 → `schlecht`, Q4 → `mittel`.** I originally scored both `mittel`
in conversation. That was wrong in both directions and the two questions are
not equivalent:

- Q3 asserts *"und den nationalen Festlegungen der ÖNORM B 1992-1-1"* while
  its only `B 1992-1-1` source is page 4, front matter. Unsourced claim →
  `schlecht`.
- Q4 gives the EN recommended k-values and says the national annexes should
  be consulted. It does not pretend to have applied them. Incomplete and
  honest → `mittel`.

Q4 is the better answer of the two even though both fall short, and the flat
`mittel` I first gave hid that.

## Trend

Q5 moved `schlecht` → `gut` and is now stable across two consecutive runs.
Q4 moved `schlecht` → `mittel`. Q1 is `gut` throughout apart from the run-2
regression, which was reverted. Q2 has been `mittel` in every run — nothing
tried so far has touched it.

Q3 is the one that has not improved under the tightened rubric. The
compound-expansion fix genuinely helped it — the EN side went from section 9
detailing rules to §6.2.3, the correct design clause — but it still claims
national provisions it cannot source, and that is what decides the grade.
Under the old scoring that improvement showed as `schlecht` → `mittel`;
under the current one it does not show at all, because the failure that
matters never went away.

### Update, 2026-08-13 — Q3 reaches `gut`

Q3 was the question that had never improved: it claimed national provisions
it could not source. It is now **`gut`**, the first time in this history.
Full detail in `2026-08-13-stages-trace-and-clause-ordering.md`; three fixes
were needed and each was invisible until the one before it landed.

1. **The register was winning every lookup.** `ÖNORM B 1992-1-1` opens with
   "Tabelle 1 — Wahlmöglichkeiten", which lists every EN clause carrying a
   national choice and so matches every clause-number lookup, while the
   clause stating the actual deviation matches one. Candidates are now
   ordered by whether they state a modification of the clause. Q3 moved to
   `mittel`: sourced to a real clause, but §9.1.1 — a *bending* Ergänzung on
   a Querkraft question.
2. **Page deduplication was blocking the right clause.** p. 21 carries both
   §9.1.1 (Biegung) and §9.2.4 (Querkraft), and parent clause 6.1 is walked
   before 6.2.3, so the bending clause took the page. The page rule now
   yields to a candidate that states the modification.
3. **`CLAUSE_LOOKUP_LIMIT` 3 → 4**, because §6.2.3 is the fourth parent
   clause walked. This is fitted to seven questions and is flagged as such.

The answer now quotes §9.2.4 verbatim — *"die Neigung der Betondruckstreben
im Bereich 0,6 ≤ tan θ ≤ 1,0"* — attributed to `ÖNORM B 1992-1-1`, alongside
the EN §6.2.3 truss model.

**Three caveats before this row is trusted.** The grade was assigned by
Claude on a single generation at non-zero temperature. The highlight check
was not run. And the answer still reproduces a corrupted `V_Rd,max`: the EN
p. 98 chunk extracts `α_cw` as `)cw` and `ν_1` as `+1`, so the model
transcribes a wrong formula faithfully — an extraction defect, tracked
separately.

The table above is **not** updated: only Q3 was re-run, and a row implies all
five. It should be regenerated in one pass, by a human, when the question set
is confirmed.
