# Eval run — 2026-08-06, compound expansion + family scope

> **Note:** scored against the rubric as it stood at the time. See `eval/runs/README.md` for the re-scoring against the current, stricter grading in `eval/questions.md`.


Follows `2026-08-06-clause-lookup.md`. Same index, retrieval-only changes.

## Two changes

**German compound expansion in BM25.** An engineer asks about
*Querkraftbemessung*; the clause is headed *Querkraft*. Those share no token,
so exact-token BM25 cannot connect them. Long query tokens are now expanded
with the corpus words they contain — corpus vocabulary rather than a
dictionary, so the parts are always terms the documents actually use.

Measured on Q3 before the change, best rank of an EN 1992-1-1 §6.2 chunk:

| BM25 query | rank |
| --- | --- |
| the question as written | 281 |
| decompounded terms | 22 |
| `Querkraft` alone | 5 |

The candidate pool is 100, and the vector channel put the same chunk at 112,
so **neither channel reached §6.2 at all** — a recall failure, not a ranking
one.

**Norm-family scope on the clause lookup.** A clause number only means
something inside one Eurocode family. Looking up EN 1992-1-1 §9.2.2
(Querkraftbewehrung) was matching ÖNORM B 1991-1-3 §9.2.2
(Schneeverwehungen) — a snow-load clause in a shear question.

## Results

| | run 5 | run 6 |
| --- | --- | --- |
| Q1 documents cited | 6, incl. EN 1990, B 1991-1-1 | **4, all timber** |
| Q3 EN §6.2 (p. 93–100) | miss | **HIT** (p. 97, 98) |
| Q4 EN §6.5.4 (p. 120–123) | HIT | HIT |
| Q5 EN §3.1.6 (p. 36–38) | HIT | HIT |
| Q3/Q4/Q5 B target clause | miss | miss |
| Q5 conclusion | **correct** | **regressed** |

Q3 now answers from the actual shear design clause — truss model, θ strut
inclination, Gleichung (6.8) and (6.9) for V_Rd,max — instead of the section 9
detailing rules. Q1 tightened to timber documents only. Q2 unchanged.

## Q5 regressed, and the reason matters

Run 5: *"α_cc = 1,0 … **keine Abminderung**"* — correct.
Run 6: *"**Ja** … muss abgemindert werden"*, citing `ÖNORM EN 1992-2`
(**Brücken**) and 0,85 — wrong, and the same error as the original baseline.

The B evidence is **identical** between the two runs (`B 1992-1-1` pages 4,
6, 6, 6, including the overview row *"Der empfohlene Wert wird übernommen"*).
Only the ordering of the EN chunks changed. So the model saw the same
national decision and reached the opposite conclusion.

That means run 5's success was not robust. With `EN 1992-1-1` saying 1,0 and
`EN 1992-2` saying 0,85 both in context, and nothing stating which part
governs a question about a *Balken*, the answer is unstable — it turns on
context ordering rather than on the norms.

## The remaining problem is scoping, not retrieval

`ÖNORM EN 1992-2` is the **bridge** part. It appears in Q5's sources in every
run so far, for a question with no bridge context. Retrieval improvements
will not settle this: both values are legitimately in the corpus, and
nothing currently tells the system that a bridge part does not govern a
general reinforced-concrete question.

Options, none yet tried:

1. **Prompt rule** — when several parts of one Eurocode family conflict,
   prefer the general part (`-1-1`) unless the question names the specialised
   domain. Cheap, but changes every answer and relies on the model obeying.
2. **Retrieval scope** — down-rank chunks from a specialised part when the
   question carries none of its domain terms. Deterministic; needs a notion
   of what each part covers, which `services/norm_identity.py` does not have
   (it parses part *numbers*, not subject matter).
3. **Surface the conflict** — report both values with their parts and say
   which applies to what, rather than picking. Arguably the most honest
   behaviour for a tool whose promise is citation accuracy.

This is a domain decision about when a bridge norm applies, so it wants an
engineer's call rather than another retrieval experiment.

## Also still open

The B target clauses (`B 1992-1-1` §9.2 p. 21, §9.5 p. 28, §6.1.4 p. 12) are
still not retrieved in any run. The national content that *is* reached comes
from the overview table on pages 6–8, which carries the same statements. So
the information arrives; the citation points at a summary table rather than
the clause.
