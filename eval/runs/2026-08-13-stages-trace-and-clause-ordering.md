# Pipeline stages, a corrected trace, and the register that ate the lookup

Three changes, measured against the enrichment-on Austrian corpus (10,509
chunks, 565 with `raw_text`, project `efc8fda8-…`). Uncommitted at the time
of writing; PR #16 is the base.

The first two are structural and changed no answer. The third changed one,
and is the only thing here a user would notice.

## 1. The pipeline extracted into stages — a deliberate null result

`retrieve_sources()` is now a runner over named stages, each taking what it
reads and returning a **new** list, each with its budget as a parameter:

    _load_corpus → _query_plan → _dense_ranking → _lexical_ranking
    → _fuse → _rerank → _admit_annex_deltas → _clause_lookup → _assemble

Success here is the eval **not** moving, and it was checked three ways:

| check | result |
| --- | --- |
| probe table vs the committed baseline | byte-identical |
| test suite | 179 pass, **zero test changes** |
| returned `SourceChunk`s vs the pre-refactor module, all 7 questions | byte-identical (`md5 61a5e58b…` both) |

The third was done by swapping the original `services/llm.py` back in and
diffing every field of every source — filename, page, norm, edition, text
length, text prefix. The zero-test-change result is the more telling one:
every monkeypatch point the suite depends on survived, so the extraction did
not quietly move a seam the tests were holding.

Both defect classes found on 2026-08-13 are now unexpressible: no stage can
spend another's budget, and no stage mutates a list it does not own.

## 2. The trace was reporting the wrong stage

`trace.reranked_ids` was snapshotted *after* `_admit_annex_deltas()`, so the
column named for the reranker reported the reranker **plus whatever
admission had rescued**. The trace is now stage-keyed and recorded at each
stage's call site, and `eval/retrieval_probe.py` builds its columns from
`PIPELINE_STAGES` rather than a hardcoded tuple — adding a stage now adds a
column instead of requiring the probe to be edited to match.

Exactly two rows changed, both where delta admission fires:

    - | Q4 | ÖNORM B 1992-1-1 p. 28 | 37 | 75 | 23 | 12   | 12 |
    + | Q4 | ÖNORM B 1992-1-1 p. 28 | 37 | 75 | 23 | miss | 12 |
    - | Q5 | ÖNORM B 1992-1-1 p. 12 |  3 | miss | 12 | 11   | 11 |
    + | Q5 | ÖNORM B 1992-1-1 p. 12 |  3 | miss | 12 | miss | 11 |

**The reranker never retrieved either clause.** Delta admission rescued
both, and the conflated column had been crediting the cross-encoder with
them.

| stage | recall@100 before | recall@100 after |
| --- | --- | --- |
| reranked | 8/13 (0.62) | **6/13 (0.46)** |
| deltas_admitted | — (new) | 8/13 (0.62) |

So the reranker is meaningfully weaker than every run note in this repo has
said, and delta admission is carrying more than it was credited with. Three
tests had encoded the conflated meaning (`assert 3 == 6`) and were moved to
the `deltas_admitted` boundary; one now asserts that `reranked` excludes
admitted deltas, so the conflation cannot return.

## 3. The register that ate the clause lookup

Every ÖNORM B annex opens with `Tabelle 1 — Wahlmöglichkeiten`, a register
listing every EN clause carrying a national choice. It therefore contains
every clause number and matched every lookup, while the clause stating the
actual deviation matches exactly one. `_clause_reference_ids()` returned
corpus order and the caller took the first candidate, so the register won,
repeatedly: **11 of 20 clause-lookup slots** across the seven questions were
register fragments.

### The first idea was wrong

Ranking candidates by *specificity* — fewest distinct clause numbers — made
it worse. The register is chunked into pieces, and the "most specific"
candidates are single **rows** of it:

    6.1 –
    7.2 –
    3.1.6 (101)P –
    9.2.2.1 – – ÖNORM B 1992-2:2019-05 8 Tabelle 1 (fortgesetzt)

Those carry no rule at all. Density was the wrong discriminator because both
the whole table and its rows are register.

### The right one

Not "how specific is this chunk" but "does it state a modification **of**
this clause, rather than merely contain its number" — a question
`reference_resolution.extract_clause_references()` already answers, and which
delta admission already trusts to decide the same thing. It recognises
`Festlegung zu`, `Ergänzung zur`, `Erläuterung zur` and
`Nationale Festlegung zu` alike.

It collapses the candidate pool hard:

| clause | candidates | state a modification |
| --- | --- | --- |
| §6.1 | 49 | 6 |
| §6.2.3 | 41 | 10 |
| §7.2 | 36 | 8 |
| §9.2.2 | 33 | 6 |

Applied as an **ordering, not a filter**: modification-stating candidates
first, everything else keeps corpus order behind them. A corpus whose
annexes phrase deviations in a way the resolver does not parse degrades to
the previous behaviour instead of returning nothing. `sorted` is stable, so
the result stays deterministic — which matters here, because a probe rank
that moves without a change being made makes every run note incomparable.

### Measured

    - | Q3 | ÖNORM B 1992-1-1 p. 21 | miss | miss | miss | miss | miss | miss |
    + | Q3 | ÖNORM B 1992-1-1 p. 21 | miss | miss | miss | miss | miss |   12 |

The only row that changed. `ÖNORM B 1992-1-1` §9.1.1 on p. 21 is Q3's
expected source and **had never been retrieved at any stage in any run
recorded in this directory**.

| | before | after |
| --- | --- | --- |
| final recall@100 | 8/13 (0.62) | **9/13 (0.69)** |
| register fragments in lookup slots | 11/20 | **2/20** |

The slots now hold real clauses — `9.1.1 Ergänzung zur … Abschnitt 6.1`,
`12.2.5 Festlegung zu … 9.2.2(4)`, `5.1.3.1 Nationale Festlegung zu …
3.1.6(101)`.

## What did not change

- recall@10 is 6/13 at every stage, unchanged. The recovered labels rank 11
  and 12, past that cutoff.
- Q2 still misses at every stage in both arms. Its clauses sit at dense rank
  10 and 23 and die at reranking; nothing here touches that.
- No answers were generated. This is retrieval only, so "Q3 now retrieves
  p. 21" is not the same claim as "Q3 now answers correctly".

## 4. The page rule was blocking the clause the question was about

Page-level deduplication (PR #16) assumed a citation is a page. True for the
source card, false when two distinct clauses share one. `ÖNORM B 1992-1-1`
p. 21 carries both:

    9.1.1  Ergänzung zur ÖNORM EN 1992-1-1:2015, Abschnitt 6.1     (Biegung)
    9.2.4  Festlegung zur ÖNORM EN 1992-1-1:2015, Abschnitt 6.2.3(2)  (Querkraft)

Parent clauses are walked in retrieval order, and 6.1 comes before 6.2.3. So
the bending clause took the page and the shear clause — on a question about
Querkraft — was silently dropped as a duplicate:

    7.4.2   DEDUPED (page already taken)   B 1992-1-1 p.36
    6.1     TAKEN    B 1992-1-1 p.21: 9.1.1 Ergänzung … Abschnitt 6.1
    9.2.2   TAKEN    B 1992-1-1 p.41: 12.2.5 Festlegung … 9.2.2(4)
    6.2.3   DEDUPED (page already taken)   B 1992-1-1 p.21   ← §9.2.4

The page rule now applies **only to candidates that state no modification of
the clause being looked up**. A chunk that answers *this* clause is admitted
even onto a page already represented; register fragments, which state no
modification, still are not.

### That alone was not enough

Freeing the page rule let 7.4.2's candidate through, which consumed the slot
instead — 6.2.3 is the **fourth** parent clause walked, and the budget was
three. `CLAUSE_LOOKUP_LIMIT` went 3 → 4.

**That second half is tuning against seven questions and should be read as
such.** The measured basis:

| limit | context avg | register fragments | Q3 gets §9.2.4 |
| --- | --- | --- | --- |
| 3 | 13.4 | 1 | no |
| **4** | **14.0** | **1** | **yes** |
| 5 | 14.4 | 2 | yes |
| 6 | 14.7 | 3 | yes |

Four is a local optimum, not a principled constant. Re-derive it when the
question set grows.

The reason §6.2.3 is walked fourth at all is that the reranker put a
Verformungen chunk above the Querkraft one — the same bottleneck as
everywhere else in this repo.

## 5. Graded run of Q3 — schlecht → mittel → gut

Three arms, same corpus, same question, full `chat()` path.

**Baseline (before today).** B sources were p. 4 (Vorwort) and p. 6–8 (the
register) — not one substantive clause — while asserting *"Die nationalen
Festlegungen in der ÖNORM B 1992-1-1 ergänzen diese Vorgaben"* and then
quoting `s_l,max` from the EN's own equation (9.6N). That is exactly the
failure the rubric defines as `schlecht`.

**After the candidate ordering.** The national claim became sourced to a real
clause — but to §9.1.1, a **bending** Ergänzung, on a Querkraft question.
Honest, substantive, off-topic. `mittel`.

**After the page-rule fix and limit 4.** Verified against the source:

    source [14]  9.2.4 … Abschnitt 6.2.3(2) Bei einer Spannung der
                 Biegezugbewehrung σsd = fyd ist die Neigung der
                 Betondruckstreben im Bereich 0,6 ≤ tan θ ≤ 1,0 zu wählen.

    answer       Bei einer Spannung der Biegezugbewehrung σ_sd = f_yd ist die
                 Neigung der Betondruckstreben im Bereich 0,6 ≤ tan θ ≤ 1,0
                 zu wählen (ÖNORM B 1992-1-1).

Verbatim, correctly attributed, and modifying precisely §6.2.3(2) — the
truss-model clause the question is about. Both p. 21 chunks are now in
context and the model used the right one. Checks 1 (substantive annex clause)
and 2 (right clause) pass; check 3 (highlight) is untested. **`gut`.**

### The probe could not see this

Q3's gold label is page-level, so `B 1992-1-1` p. 21 scored a hit at rank 12
in *both* the `mittel` and the `gut` arm. Final recall@100 is 9/13 in both.
The page-level label masked a clause-level miss, and only the graded run
distinguished them. Worth remembering the next time a null probe result is
read as "no change".

## 6. Greek letters surviving as printable ASCII — found and fixed

The `gut` answer still gets `V_Rd,max` wrong:

    answer   V_Rd,max = ν_cw b_w z + α_1 f_cd/(cot θ + tan θ)
    EN (6.9) V_Rd,max = α_cw · b_w · z · ν_1 · f_cd / (cot θ + tan θ)

The model is not hallucinating. The source chunk, `EN 1992-1-1` p. 98, reads:

    VRd,max = )cw bw z +1 fcd/(cotθ + tanθ )   (6.9)

`α_cw` extracted as `)cw`, `ν_1` as `+1`. This is an **extraction** failure,
not a generation one. `services/symbol_text.py` recovers Greek letters that
land as control characters; these land as printable ASCII, which that fix
deliberately leaves alone because translating printable codes rewrote
ordinary letters (62,269 bogus Greek characters, the first attempt).

A user-visible wrong formula in a product whose promise is citation accuracy.

### The fix: font-attributed, layout-preserving translation

The spans carry the font, and on that very line they separate the two cases
cleanly:

    SymbolMT   ')'                ← α
    ArialMT    'cw '
    SymbolMT   '+'                ← ν
    ArialMT    '/(cot + tan )'    ← real "+" and ")", must not be touched

`_decode_per_span()` already decoded with font attribution but was only a
fallback, because it rebuilds the page from spans and **differs from
`get_text()` on all 250 pages of ÖNORM EN 1992-1-1** — it inserts a blank
line between blocks. Using it everywhere would move every chunk boundary and
every boilerplate match in the corpus.

So `_translate_symbol_spans()` locates each span in the flat `get_text()`
string with an advancing cursor and replaces one character with one
character in place. Wherever nothing is translated the output is
byte-identical to `get_text()`.

### Two guards, both added after measurement, not before

The first attempt over-reached and the corpus said so:

- `3 4 5 6 7 8` became `⇐ ⇔ ∨ ⊂ ⊄ ⊇` on EN 1991-1-4 p. 112. Those are
  large-bracket assembly glyphs at high glyph ids, and the GID+29 offset —
  derived from exactly two glyphs, α at /g68 and γ at /g74 — does not hold
  there. Printable codes are now admitted **only into the Greek block**.
- Three newlines became `ηηη` on p. 110, running three formula lines
  together. Layout whitespace is now never translated, at the cost of a few
  genuine recoveries that sat on a tab.

Control codes keep the full table: no text font emits them, and that mapping
has been in use since the original fix.

### Measured over all 39 PDFs

| | before | after |
| --- | --- | --- |
| Greek characters | 6,315 | **6,925** (+610) |
| residual control characters | 0 | 0 |
| non-Greek outputs from printable codes | — | **0** |

Every spot check is verifiable from its own context: `Durchmesser von φ >
bw/8`, `VEd,red = VEd – ΔVEd` (6.48), the strain labels `ε = 0` and `ε1`,
`Re … ν`, `Sν(z,n)`, and `Anströmrichtung Θ = 0`.

### Re-ingested and re-run

New project, 39/39 files, 10,511 chunks, 565 enriched. **The probe does not
move**: final recall stays 9/13, every stage unchanged. Individual ranks
shift slightly — Q3's EN gold 8 → 7, and Q4's EN gold improves to dense 3 and
fused 1, though the reranker still drops it.

The graded Q3 stays `gut` and improves inside the grade:

    before  V_Rd,max = ν_cw b_w z + α_1 f_cd/(cot θ + tan θ)     wrong
    after   V_Rd,max = α_cw b_w z ν_1 f_cd/(cot θ + tan θ)       matches (6.9)

It also began citing clause numbers rather than documents —
*"(ÖNORM B 1992-1-1, Abschnitt 9.2.4)"*, *"(ÖNORM EN 1992-1-1, Abschnitt
6.2.3)"* — which is what check 2 of the rubric asks for.

**The probe could not see this either.** Recall is identical before and
after. A wrong formula reached a reader and only a graded run caught it —
the second time in one day that the probe was blind to something that
mattered.

## Reading

The ordering this repo committed to — fix quality first, refactor later —
held up. The stage extraction and the trace fix improved **no answer at
all**; their value was diagnostic, and real: without separating the stages
we would still believe the reranker had recall@100 of 8/13. Everything that
moved an answer was a retrieval-quality fix that needed no architecture.

Q3 is the first question in this repo's history to move to `gut`, and it
took three separate fixes to get there: order candidates by whether they
state a modification, stop the page rule from blocking a second clause on a
taken page, and give the lookup a fourth slot. Each was invisible to the
stage before it.

Worth carrying: the reranker is now measured as worse than assumed, which
strengthens the case for routing *around* it (levels 3–5) rather than
continuing to look for a better one — a swap to `BAAI/bge-reranker-v2-m3`
already failed to help (`eval/runs/2026-08-08-reranker-swap.md`).

## Caveats

- Seven questions, 13 gold labels, and the expected sources are still
  proposed rather than engineer-confirmed. One label moving is suggestive,
  not conclusive.
- The Q3 grade was assigned by Claude, on one generation per arm at non-zero
  temperature. It is a single sample judged by its own author.
- The highlight check was never run in any arm. The symbol fix should help
  it — `search_for()` fails outright on strings containing unresolved
  glyphs — but that is an expectation, not a measurement.
- `CLAUSE_LOOKUP_LIMIT = 4` is fitted to this seven-question set.
- Two register fragments still reach the lookup (Q3 `B 1992-1-1` p. 8, Q6
  p. 5), where no candidate states a modification of the clause in question.
  That is the fallback behaving as designed.
- Duplicate pages from the reranker and delta admission are untouched; page
  deduplication was added to the clause lookup only.
