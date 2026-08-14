# Retrieval probe — 2026-08-13

Headless retrieval-only run (`python -m eval.retrieval_probe`) against
project `ae530fd6-f569-4221-b9fc-09d7d1a3308b`. No answer was generated and no chat completion
was called; the query embedding is the only model call. Gold labels come
from the `gold` blocks in `eval/questions.md`, and a chunk counts as a
hit when its `norm_reference` and `page_number` metadata match one.

Each cell is the 1-based rank of the first matching chunk at that
stage, or `miss`. Stages are in pipeline order; `reranked` and `final`
are cut to context size, so a `miss` there with a hit upstream
localizes where the chunk was lost.

| question | gold | dense | lexical | fused | reranked | deltas_admitted | final |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Q1 | `ÖNORM EN 1995-1-2` any page | 4 | 4 | 2 | 3 | 3 | 3 |
| Q1 | `ÖNORM B 1995-1-2` any page | 2 | miss | 11 | 1 | 1 | 1 |
| Q2 | `ÖNORM EN 1995-1-2` p. 25, 35, 36 | 10 | miss | 24 | miss | miss | miss |
| Q2 | `ÖNORM B 1995-1-2` p. 7 | 24 | miss | 50 | miss | miss | miss |
| Q3 | `ÖNORM EN 1992-1-1` p. 93, 97, 98 | 78 | 2 | 3 | 7 | 7 | 7 |
| Q3 | `ÖNORM B 1992-1-1` p. 21 | miss | miss | miss | miss | miss | 12 |
| Q4 | `ÖNORM EN 1992-1-1` p. 120 | 3 | 8 | 1 | miss | miss | miss |
| Q4 | `ÖNORM B 1992-1-1` p. 28 | 38 | 77 | 24 | miss | 12 | 12 |
| Q5 | `ÖNORM EN 1992-1-1` p. 36 | miss | 18 | 43 | miss | miss | miss |
| Q5 | `ÖNORM B 1992-1-1` p. 12 | 3 | miss | 12 | miss | 11 | 11 |
| Q6 | `ÖNORM EN 1992-1-1` p. 56, 57 | 2 | 3 | 2 | 2 | 2 | 2 |
| Q6 | `ÖNORM B 1992-1-1` p. 13, 14 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q7 | `ÖNORM EN 1992-1-1` p. 66 | 1 | 2 | 1 | 1 | 1 | 1 |

## Recall across the question set

Fraction of gold labels ranked at or above the cutoff, per stage.

| stage | recall@10 | recall@100 |
| --- | --- | --- |
| dense | 8/13 (0.62) | 11/13 (0.85) |
| lexical | 6/13 (0.46) | 8/13 (0.62) |
| fused | 6/13 (0.46) | 12/13 (0.92) |
| reranked | 6/13 (0.46) | 6/13 (0.46) |
| deltas_admitted | 6/13 (0.46) | 8/13 (0.62) |
| final | 6/13 (0.46) | 9/13 (0.69) |
