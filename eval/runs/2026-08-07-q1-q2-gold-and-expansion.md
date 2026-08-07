# Q1/Q2 gold labels, and query expansion measured on its own target

Q1 and Q2 had no gold blocks, so the probe skipped them. That mattered more
than it looked: **PR #11 exists for the "Q2 charring gap", and the A/B that
approved it measured Q3, Q4 and Q5 — never Q2.** Both are now labelled.

Q1 needed a format change. It asks which norms apply, so the expectation is
that a chunk of each document reaches the context, not that a particular
clause does. Pinning it to a page would measure something the question never
asks, and listing every page of the PDF would express the same thing while
looking like a claim about clauses. The gold format now accepts `*` for a
document-level label.

Q2's labels are the pages of the expected sources already in the file:
`EN 1995-1-2` §3.4.2 (p. 25), §4.2.2 (p. 35), §4.2.3 (p. 36), and
`B 1995-1-2` §6.1 *Abbrandtiefe* (p. 7). Located in the documents; still not
signed off as the *right* answer for R60.

## Q1 — passes at retrieval level, both arms

| gold | dense | lexical | fused | reranked | final |
| --- | --- | --- | --- | --- | --- |
| `EN 1995-1-2` any page | 4 | 4 | 2 | 3 | 3 |
| `B 1995-1-2` any page | 2 | 90 | 11 → 1 | 1 | 1 |

Both documents reach the final context either way, consistent with Q1
grading `gut` end to end. Expansion improves the annex's fused rank (11 → 1)
without changing the outcome.

## Q2 — expansion does not fix it

| gold | dense | lexical | fused (off → on) | reranked | final |
| --- | --- | --- | --- | --- | --- |
| `EN 1995-1-2` p. 25, 35, 36 | 10 | miss | 26 → 11 | miss | miss |
| `B 1995-1-2` p. 7 | 22 | miss | 47 → 58 | miss | miss |

Expansion moves the EN charring clauses up the fused ranking (26 → 11) and
moves the Austrian one *down* (47 → 58). Neither survives reranking in
either arm, so **the answer is unchanged and Q2 stays `mittel`.**

## This contradicts the premise #11 was built on

The PR argues the charring content is unreachable because the question never
says *Abbrandtiefe* or *Restquerschnitt*, and that no downstream mechanism
can bridge terms absent from the query. The first half is right about
lexical retrieval — BM25 **misses those clauses entirely in both arms**, and
compound splitting cannot help because the question and the clause share no
substring.

But dense retrieval already ranks them **10th and 22nd**. They are not
unreachable; they are reachable and then discarded. Q2's failure is a
reranking failure, not a recall failure — the same conclusion the Q3–Q5 A/B
reached, now confirmed on the question that motivated the feature.

## Consequence

Query expansion is measurably useful at the fusion stage across all five
questions, and measurably useless end to end on every one of them,
including its own target. It should stay flagged off, and the ticket it
closes should be reopened against the reranking stage rather than treated
as resolved.

The cross-encoder scores `(question, chunk)` pairs. A clause headed
*Ungeschützte Oberflächen während der gesamten Branddauer* has little
surface overlap with a question about fire-resistance class R60 for a timber
beam, exactly as `"Der empfohlene Wert wird übernommen"` has none with a
question about concrete strength. Both are the same failure at the same
stage.
