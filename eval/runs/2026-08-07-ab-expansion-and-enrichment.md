# A/B — query expansion (#11) and annex reference enrichment (#13)

Measured with `backend/eval/retrieval_probe.py` (merged in #12), which
reports where each gold chunk ranks at every pipeline stage. Retrieval only:
no answer generation, no chat completion.

Corpus: the 39 Austrian ÖNORM PDFs, ingested into a dedicated project so the
demo projects were not mutated. Query expansion is a query-time flag, so both
arms ran against one index. Enrichment is index-time, so arm B is the same
project after `enrich_project_references()` — identical corpus, enrichment
the only difference. **555 chunks were enriched.**

## Fused-stage recall, the stage each feature targets

| | dense @100 | lexical @100 | fused @100 | fused @10 |
| --- | --- | --- | --- | --- |
| neither | 2/6 (0.33) | 4/6 (0.67) | 3/6 (0.50) | 2/6 (0.33) |
| expansion only | 2/6 (0.33) | 3/6 (0.50) | 4/6 (0.67) | 2/6 (0.33) |
| enrichment only | 4/6 (0.67) | 4/6 (0.67) | 5/6 (0.83) | 2/6 (0.33) |
| **both** | 4/6 (0.67) | 4/6 (0.67) | **6/6 (1.00)** | **5/6 (0.83)** |

Both work, and they are complementary rather than redundant — together they
put **every** gold chunk into the candidate pool, five of six inside the top
ten.

The headline case: `ÖNORM B 1992-1-1` §6.1.4, the α_cc clause that reads only
*"Der empfohlene Wert wird übernommen."* It has been unreachable at every
stage in every run recorded here. With enrichment it ranks **3rd on dense
retrieval**.

## What neither changes

| stage | neither | expansion | enrichment | both |
| --- | --- | --- | --- | --- |
| reranked | 1/6 | 1/6 | 1/6 | 1/6 |
| final | 1/6 | 1/6 | 1/6 | 1/6 |

Every chunk the two features recover is discarded by the cross-encoder. The
end-to-end effect of enabling either, or both, is **zero as measured**.

**The bottleneck has moved.** Through every earlier run the problem was
recall: the deciding clause was not in the pool, so nothing downstream could
use it. That is now fixed. The cross-encoder receives the right chunks and
throws them out — five of the six it is handed.

The likely cause is the same vocabulary problem one stage later. The
reranker scores `(question, chunk)` pairs, and a delta clause reading *"Der
empfohlene Wert wird übernommen"* has nothing lexical or semantic to match a
question about concrete compressive strength. Its parent-clause heading now
makes it *findable*; it does not make it *score*.

## Recommendation

Both merged, both flags left **off**. Enabling them buys nothing while the
reranker discards their output, and expansion costs an LLM call per question.
Turn them on in the same change that addresses the reranking stage, and
re-run this probe to confirm the recall gain survives to `final`.

## Smaller findings

- **Enrichment costs Q3 its annex clause.** `B 1992-1-1` p. 21 went from
  lexical rank 97 to `miss`: appending parent headings to 555 chunks shifts
  BM25 term statistics corpus-wide. Recovered at the fused stage with
  expansion also on (rank 26), but a real if minor regression on its own.
- **Unresolved references are left alone rather than guessed.** Enrichment
  logged `EN 1997-1 Abschnitt 11.5.1 (clause heading not found); chunk left
  unenriched` — the correct behaviour for a tool whose promise is citation
  accuracy.
- **Q4 and Q5 gold labels remain too narrow.** They name one page of a
  multi-page clause (Q4 §6.5.4 spans 120–123; Q5's deciding sentence is on
  p. 37, not the p. 36 heading). Absolute recall is therefore understated in
  every row above. The A/B deltas are unaffected, since both arms are scored
  against identical labels.
