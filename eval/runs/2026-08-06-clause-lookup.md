# Eval run — 2026-08-06, two-pass clause lookup

> **Note:** scored against the rubric as it stood at the time. See `eval/runs/README.md` for the re-scoring against the current, stricter grading in `eval/questions.md`.


Follows `2026-08-06-front-matter-and-labels.md`. Same corpus (39 Austrian
ÖNORM PDFs; the German `Normen-2/` set is still not ingested), same index —
ingestion did not change, so this measures the retrieval change alone.

**This is a retrieval change**, unlike the previous two. `.claude/prioritization.md`
requires an evaluation method for those; this file is the result.

## What changed

After the normal pass, take the clause numbers the results landed on
(read from the heading the chunker prepends) and look them up literally in
other documents. A national annex states its rule as a delta —
*"Festlegung zu ÖNORM EN 1992-1-1:2015, Abschnitt 3.1.6(1)P — Der empfohlene
Wert wird übernommen."* — so the clause number is the only token it shares
with anything. Up to 3 such chunks are appended, never substituted.

## Result: Q5 is now correct

| | before | after |
| --- | --- | --- |
| conclusion | *"**Ja**, … muss abgemindert werden"* | *"α_cc = 1,0 … **keine Abminderung**"* |
| value used | **0,85**, from `ÖNORM EN 1992-2` (**Brücken**) | **1,0**, from `EN 1992-1-1` §3.1.6 |
| national decision | never retrieved | *"die empfohlenen Werte werden übernommen"* |

The answer now reaches the Austrian decision and stops borrowing the bridge
value for a question with no bridge context. This is the failure the question
set was built to catch, and it is fixed.

Q4 also improved: it now names `ÖNORM B 1992-1-1` as the applicable national
supplement and cites EN §6.5.4(4)a) explicitly. Q1, Q2 and Q3 are unchanged;
nothing regressed.

## What it reaches, and what it still does not

Q5 succeeds via `ÖNORM B 1992-1-1` **p. 6**, the *"Übersicht über die
Abschnitte mit nationaler Wahlmöglichkeit"* table, whose row reads
`6.1.3 / Der empfohlene Wert wird übernommen. / – / 3.1.6(1)P`. That carries
the same statement as §6.1.4 on p. 12, which is still not retrieved.

So the *information* is now reached but the *citation* points at an overview
table rather than the clause. A source card showing p. 6 is defensible but
p. 12 would be better. The lookup takes the first chunk matching a clause;
preferring the more specific match is an obvious refinement, untested.

Q3 still misses `B 1992-1-1` §9.2 (p. 21) entirely.

## A bug this run caught

The first attempt excluded *every document already present in the first
pass* from the lookup, reasoning that a norm cites its own clauses
constantly. That was too coarse: one front-matter chunk of
`ÖNORM B 1992-1-1` ranking in the first pass barred that whole document from
the second pass — the one document the lookup existed to reach. Q5 was
unchanged and the mechanism looked useless.

Excluding only the document each clause *came from* fixes it. Pinned by
`tests/test_clause_lookup.py::test_an_annex_already_in_the_results_is_still_searchable`.

## Cost

Sources per answer rise from 10 to as many as 13, so the context sent to the
model grows by up to 30%. No extra embedding, vector or reranker work: the
lookup is a substring scan over the corpus already fetched for BM25.
