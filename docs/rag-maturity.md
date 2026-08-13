# Where this RAG sits

An assessment of NormChat's retrieval architecture against the levels the
field uses, written 2026-08-12 against `main` at `54feca8`. Every claim
below points at code or at a run note, so it can be checked rather than
taken on trust.

## The five levels

Two taxonomies are in common use. This one grades **architecture**:

| | level | defining move |
| --- | --- | --- |
| 1 | **Naive** | chunk, embed, similarity search, stuff the prompt |
| 2 | **Advanced** | hybrid dense + sparse, reranking, query rewriting, smarter chunking — the same linear pipeline with better components |
| 3 | **Modular** | components become swappable and composable; routing and validation appear |
| 4 | **Graph / structure-aware** | the flat index is augmented by relations between documents, and retrieval becomes traversal |
| 5 | **Agentic** | the pipeline judges itself — Self-RAG's retrieve-and-critique tokens, CRAG's relevance evaluator and corrective re-retrieval |

The second, the RAG Maturity Model (RMM-0…5), grades **production
readiness** instead — recall, precision, trust, workflow, enterprise
controls. Both are used below, because this system scores very differently
on them.

## Verdict: level 2 of 5, with a genuine slice of level 4

### Level 2 is complete, and unusually thorough

- Hybrid retrieval: dense vectors and BM25 merged by reciprocal rank fusion
  — `services/llm.py`, `services/reranking.py`
- Cross-encoder reranking — `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`
- Query expansion, built and measured, deliberately left off —
  `services/query_expansion.py`
- German compound expansion, because *Querkraftbemessung* and *Querkraft*
  share no token: it moved the §6.2 clause from BM25 rank 281 to 22
  (`eval/runs/2026-08-07-ab-expansion-and-enrichment.md`)

The chunking stack is the part most systems never build: clause-aware
splitting with heading carry-over, boilerplate and front-matter stripping,
Symbol-font glyph recovery (5,372 control characters to zero), and Markdown
table serialisation.

### Level 3 is partial

The reranker is swappable by config and was in fact swapped
(`eval/runs/2026-08-08-reranker-swap.md`); two features sit behind flags.
But there is no router, no validator, and no component registry. It is a
fixed pipeline with knobs, not a composable one.

### Level 4 is real, narrow, and deliberately not a graph

The clause-lookup → enrichment → delta-admission chain resolves references
*between* documents and retrieves along them. `ÖNORM B 1992-1-1` §6.1.4 —
which reads, in full, *"Festlegung zu ÖNORM EN 1992-1-1:2015, Abschnitt
3.1.6(1)P — Der empfohlene Wert wird übernommen"* — is found because it
names its parent clause, not because it resembles the question. That is the
relation half of GraphRAG without the graph.

The graph itself was considered and rejected on evidence; `docs/norm-graph.md`
records why, and a clause-number lookup got the win for a fraction of the
cost.

### Level 5 is absent

Nothing decides *whether* to retrieve, nothing critiques what came back,
nothing re-retrieves on low confidence. The nearest thing is
`_parts_in_conflict()`, which detects that two parts of one Eurocode were
retrieved and requires the answer to contrast them rather than silently
pick — deterministic and narrow, not agentic. It was added because the
answer to Q5 flipped between runs on context ordering alone.

## Against the production-readiness model

| | | |
| --- | --- | --- |
| RMM-1 | recall — hybrid retrieval | done, and measured per stage |
| RMM-2 | precision — reranking | done; measurement showed the reranker is now the bottleneck |
| RMM-3 | trust — faithfulness, guardrails | **partial**: citations mandatory, generated text never presented as quotation, highlights grounded in real page text — but no faithfulness scoring, no guardrails, no PII handling |
| RMM-4 | workflow — caching, latency, cost | **weak**: retrieval is O(corpus) per query, ~6 s warm on the 20k-chunk German corpus, no caching, no cost tracking |
| RMM-5 | enterprise — CI gates, drift | **partial**: CI runs on pull requests, but a merge to `main` does not trigger an evaluation run |

## The honest limitation

The thing this repository does best — measuring changes, recording
regressions, reverting features that fail to earn their place — rests on a
**seven-question golden set whose expected sources were proposed by Claude
and have never been confirmed by an engineer**, two of whose questions
(Q6, Q7) Claude also wrote.

For scale: the maturity model's criterion for its *first* level is recall@5
above 70% on a golden set of **at least 50 questions**. This set has 7, and
final-stage recall of 5/12.

So the accurate summary is not "level 2.5 with good evaluation". It is:

> **Level 2.5 with unusually good evaluation *practice*, at a scale too
> small to support the confidence that practice implies.**

Every conclusion in `eval/runs/` is directionally sound and statistically
thin. Two of them have already been corrected by later measurement — a
"fabricated" table that turned out to exist, and an image count overstated
roughly sevenfold.

## What would raise the level

Not architecture. Confirming and expanding the question set would do more
for this system than any move toward levels 3–5 — it is the precondition
for trusting anything those levels would be judged by.

After that, the measured constraints in order: the reranker discards
annex clauses handed to it at fused rank 3 (levels 3–5 all bear on this),
and O(corpus) retrieval caps both latency and instance size.

## Sources

- [The 5 Levels of RAG Maturity](https://dev.to/hallengray/the-5-levels-of-rag-maturity-how-to-know-when-your-rag-is-actually-production-ready-33o5)
- [RAG architecture patterns](https://atlan.com/know/rag-architecture/)
- [Agentic RAG: a survey](https://arxiv.org/pdf/2501.09136)
- [RAG maturity: stages, metrics, anti-patterns](https://ombrulla.com/insights/rag-maturity-model-stages-metrics-anti-patterns)
