# Cross-encoder swap — 2026-08-08

Every measurement to that point put the bottleneck at reranking: with
enrichment and expansion on, fused recall reached 6/6 while `final` stayed
at 1/6. The cross-encoder was being handed the right chunks and discarding
them. The obvious hypothesis was that the model was too small, so it was
swapped for a much larger one.

Tested: `BAAI/bge-reranker-v2-m3` against the shipping
`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`.

| | shipping | BGE-v2-m3 |
| --- | --- | --- |
| parameters | 118M | **568M** |
| max sequence | 512 | **8192** |
| full-pipeline peak RSS | 697 MB | 826 MB |

Memory was not the obstacle — 826 MB still fits the 2 GB instance.

## It did not fix it

Enriched corpus, both features on:

| stage | shipping | BGE |
| --- | --- | --- |
| fused recall@100 | 10/10 | 10/10 |
| **reranked / final** | **3/10** | **4/10** |

One extra chunk survived. What it still discarded is the point:

| gold | fused rank | reranked |
| --- | --- | --- |
| Q5 `B 1992-1-1` p. 12 | **3** | miss |
| Q4 `B 1992-1-1` p. 28 | **8** | miss |
| Q3 `B 1992-1-1` p. 21 | 21 | miss |

Q5's annex clause arrives **third out of a hundred** and a 568M-parameter
multilingual reranker pushes it out of a top ten.

At answer level Q5 got **worse**. It surfaced the EN/bridge conflict and
named the scopes, but contained zero mentions of `B 1992-1-1` or
"übernommen" — it never reached the Austrian decision and deferred to the
engineer. Level 6 to level 5.

## Conclusion

The failure survives a 4.8x larger model with 16x the context, trained on
the same multilingual passage-ranking objective. Both models rank *"Der
empfohlene Wert wird übernommen"* below ten other chunks when the question
is about concrete strength, because relevance-by-reference is not something
either was trained to represent.

The mismatch is in the objective, not the capacity. That is what justified
`_admit_annex_deltas()` in `services/llm.py`: not asking the reranker to
judge these chunks at all, rather than hoping a better one would.

BGE was removed afterwards; the model cache is back to the shipping
reranker alone.
