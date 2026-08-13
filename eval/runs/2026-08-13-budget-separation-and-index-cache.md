# Budget separation and the lexical index cache

Two defects found by reading `retrieve_sources()`, both from pipeline stages
sharing state they never declared. This is the probe run CLAUDE.md requires
for a deliberate retrieval change.

Project: a fresh 39-file Austrian corpus, ingested with reference enrichment
on — **10,509 chunks, 565 carrying `raw_text`**. This mattered: none of the
three projects already on disk were enriched (`raw_text=0` on all of them),
so delta admission was inert and the probe would have produced a null result
that proved nothing.

## The gold-label table does not move

Identical, cell for cell, on `main` (19d3da1) and on the fix. Recall@10 stays
6/13 and recall@100 stays 8/13 at every stage.

That is the intended result for the index cache, which is a pure performance
change. It is **not** the whole story for the budget fix, which the probe
cannot see: the probe measures where gold labels rank, and the budget
governs how many *additional* chunks the second pass may append.

## The budget was contended on exactly two questions

| question | deltas admitted | clause lookups (main) | clause lookups (fixed) |
| --- | --- | --- | --- |
| Q1, Q2, Q3, Q6, Q7 | 0 | 3 | 3 |
| Q4 | 2 | **1** | **2** |
| Q5 | 2 | **1** | **3** |

The lookup capped itself at `len(final_ids) >= top_k + 3`, and
`_admit_annex_deltas` appends to that same list first. Two admissions
therefore left one slot instead of three — and only on the annex-heavy
questions, because those are the only ones where deltas are admitted at all.
The mechanism was silently weakest exactly where it was meant to work.

## What the recovered slots actually contain — the uncomfortable part

Q4 recovered `ÖNORM B 1992-2` p. 29, a real national modification
("11.6 Gründungen — Nationale Festlegung zu ÖNORM EN 1992‑2:2012, Abschnitt
9.8.1(103)") — but from the **bridge** part, on a question about node design
in a building.

Q5 recovered two more fragments of `ÖNORM B 1992-1-1` **p. 6**, a page it had
already retrieved. All three lookups on Q5 are pieces of the same
"Tabelle 1 (fortgesetzt)" continuation table.

Counting duplicate pages in the final context:

| question | repeated pages |
| --- | --- |
| Q4 | `EN 1992-1-1` p. 122 ×2, `B 1992-1-1` p. 4 ×2 |
| Q5 | `B 1992-1-1` p. 6 ×3, `B 1992-1-1` p. 12 ×2 |

So the fix restores budget to a mechanism whose **selection** is weak. It
gives the lookup its declared three slots and the lookup spends them on
near-duplicates.

## What did not go wrong

`_parts_in_conflict()` returns the same result on both arms
(`1992: [1992-1-1, 1992-2]` on Q4 and Q5). The out-of-part bridge clause was
already present in main's top 13, so the recovered chunk introduces no new
conflict and cannot regress the answer through that path. An earlier
suspicion that it might was wrong.

## Page-level deduplication, added in response

A citation in this product is a page: two chunks of one page open the same
source card on the same highlight, so the second buys the user nothing and
costs context. The lookup now skips any candidate whose (document, page) is
already represented — seeded from `final_ids`, so pages the reranker or
delta admission already placed are covered too.

**Measured:** the gold-label table is again identical, and **zero** lookup
chunks now land on an already-covered page (was 2 on Q5 alone). Q5 still
fills all three slots; they are simply three different pages now.

Remaining duplicate pages in the final context all come from the reranker
and delta admission, which this change does not touch:

| question | repeated pages after dedupe |
| --- | --- |
| Q4 | `EN 1992-1-1` p. 122 x2, `B 1992-1-1` p. 4 x2 |
| Q5 | `B 1992-1-1` p. 12 x2 |
| Q6 | `EN 1992-1-1` p. 57 x3, `B 1992-1-1` p. 13 x2, p. 14 x2 |
| Q7 | `EN 1995-1-1` p. 55 x2 |

## What the dedupe exposed in turn

Q5's three slots are now three distinct pages — and all three are still
`Tabelle 1 (Wahlmöglichkeiten)`, the annex's **index of national choices**:

    B 1992-1-1 p. 6   Tabelle 1 (fortgesetzt) | Abschnitt gemaess OENORM EN 1992-1-1 ...
    B 1992-1-1 p. 8   Tabelle 1 (fortgesetzt) | Abschnitt gemaess OENORM EN 1992-1-1 ...
    B 1992-2   p. 7   Tabelle 1 - Wahlmoeglichkeiten | Abschnitt gemaess OENORM EN 1992-2 ...

That table lists *every* EN clause carrying a national choice, so it
contains every clause number and therefore matches every clause-number
lookup. It is a magnet, and the lookup keeps hitting it instead of the
substantive `Festlegung zu ...` clause.

This matters beyond context economy: the grading rules in
`eval/questions.md` state that a cited annex must be a **substantive
clause**, and that a cover, foreword or contents page does not count. An
index table is exactly that kind of non-substantive hit. **The clause lookup
is spending its budget on content the rubric says does not count** — a
better ticket than either defect fixed here.

## Reading

- **The index cache is safe to take.** Identical retrieval output, and the
  identical probe table is the proof. Measured on the 20k-chunk German
  corpus: 0.77 s to build, 0.03 s cached. Retrieval on that corpus is
  ~4.3 s, of which `collection.get()` is 1.11 s and the cross-encoder pass
  over 100 pairs is 2.19 s — so this is roughly a 17% saving with defaults,
  and ~3 s with query expansion on, which rebuilt the index five times per
  request.
- **The budget fix is correct but not demonstrably valuable here.** No gold
  label moves, no new part conflict, no regression — and what it recovers is
  mostly the same page again. It should not be sold as a quality
  improvement on this evidence.
- **A third defect is now visible:** the clause lookup has no page-level
  deduplication. `_leading_clause_numbers` yields several parent clauses,
  each resolves independently, and nothing stops three of them landing on
  three chunks of one continued table. That is a better ticket than the
  budget was.

## Caveat

Seven questions, and their expected sources are still proposed rather than
engineer-confirmed. A null result on a set this small is weak evidence of
no harm, not evidence of no effect.
