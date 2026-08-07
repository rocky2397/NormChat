# Eval run — 2026-08-07, cross-encoder ablation

Run to answer a hosting question, not a retrieval one: the cross-encoder is
what forces a 2 GB instance on Render ($25/month versus $7 for 512 MB), so
the question was whether dropping it is an acceptable trade.

Method: `rerank_ids` patched in-process to return the fused
(vector + BM25) order unchanged. Nothing in the repo was modified. Run
against the ÖNORM demo project, 9,579 chunks, same five questions.

## Answer: no, on two independent grounds

### 1. It does not even fit the smaller instance

| | with cross-encoder | without |
| --- | --- | --- |
| imports | 440 MB | 313 MB |
| + full corpus held in memory | — | 502 MB |
| + BM25 fit and scored | 887 MB | **553 MB** |

553 MB already exceeds a 512 MB instance, on the *smaller* of the two
corpora — the DIN project has more than twice the chunks. The reranker is
not what makes this app too big for 512 MB; `retrieve_sources` loading the
entire corpus and refitting BM25 on every query is. Removing the
cross-encoder alone buys nothing at the hosting level.

### 2. Quality collapses on the question that matters most

| | reranker on | reranker off |
| --- | --- | --- |
| Q3 EN §6.2 (p. 93–100) | HIT | HIT (more diffuse) |
| Q4 EN §6.5.4 (p. 120–123) | HIT | HIT |
| Q5 EN §3.1.6 (p. 36–38) | HIT | **MISS** |
| Q5 grade | 6 | **1 — wrong rule applied** |

Q5 without the reranker:

> "…sofern der empfohlene Wert von **0,85** für α_cc verwendet wird."

That is the value from `ÖNORM EN 1992-2` — the **bridge** part — applied to
a general question about buildings. `EN 1992-1-1` §3.1.6, which recommends
1,0, was never retrieved. This is precisely the baseline failure this work
set out to fix, reproduced exactly.

The source list shows why. Without the cross-encoder, Q5 pulls front matter
from ten different documents — `B 1991-1-5`, `EN 1990`, `B 1995-1-2`,
`B 1990-1`, `EN 1991-1-4`, `B 1993-1-5` — snow, timber, wind and steel
norms in a concrete question, mostly pages 3–5. Reciprocal rank fusion puts
them in the pool; the cross-encoder is what throws them out.

## A limit of the conflict mechanism, worth recording

`_parts_in_conflict` correctly detected parts 1992-1-1 and 1992-2 together
and issued its warning, and the answer still went wrong. It can only
contrast values that were retrieved, and here only the bridge value was.
**Conflict surfacing is downstream of retrieval quality and cannot
substitute for it.**

## Decision

Keep the cross-encoder. It is doing discrimination work that nothing else in
the pipeline does, and dropping it would not have reduced the instance size
anyway.

If the 2 GB requirement is ever worth attacking, the target is the O(corpus)
retrieval — caching the tokenised corpus and BM25 index per project, which
only changes on upload — not the reranker.
