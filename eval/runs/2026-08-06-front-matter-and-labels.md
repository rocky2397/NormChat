# Eval run — 2026-08-06, after two fixes

> **Note:** scored against the rubric as it stood at the time. See `eval/runs/README.md` for the re-scoring against the current, stricter grading in `eval/questions.md`.


Follows `2026-08-06-baseline.md`. Same corpus (39 Austrian ÖNORM PDFs, the
German `Normen-2/` set was **not** ingested), same settings, same isolated
sandbox project. **No retrieval or ranking code was changed in either fix** —
`retrieve_sources`, BM25, RRF and the cross-encoder are untouched. What
changed is the text that gets indexed, and post-processing of the answer.

Three runs:

| | run 1 baseline | run 2 cover+TOC+foreword | run 3 cover+TOC only |
| --- | --- | --- | --- |
| chunks | 11,834 | 9,512 | 9,579 |
| Q1 citation labels | **leaked** | fixed | fixed |
| Q1 annex described correctly | yes | **no — regressed** | yes |
| Q3 target `B 1992-1-1` §9.2 p.21 | miss (p. 4, 1, 4) | miss (p. 4) | miss (p. 4) |
| Q4 target §9.5 p.28 | miss (p. 4, 1) | miss (p. 4, 68, 47) | miss (p. 4, 4) |
| Q5 target §6.1.4 p.12 | miss (p. 4) | miss (p. 54) | miss (p. 4) |

Run 3 is the state that was kept.

## Fix 1 — citation labels: works

`_replace_citation_labels` now matches bracketed, parenthesised and bare
labels, with any index list. Q1's baseline output `"(siehe Quelle 1 und 2)"`
became `"(ÖNORM B 1995-1-2)"`. No label leaked in runs 2 or 3.

## Fix 2 — front matter: partly reverted

Blanking **covers and contents pages** was kept. Blanking **forewords** was
tried in run 2 and reverted, because it broke Q1:

- baseline: *"ÖNORM B 1995-1-2: Diese Norm enthält nationale Erläuterungen
  und Ergänzungen zur ÖNORM EN 1995-1-2 und ist gemeinsam mit dieser
  anzuwenden."* — correct.
- run 2: *"Diese Norm ist die konsolidierte Fassung von ÖNORM EN 1995-1-2"*
  — wrong. That phrase describes the EN document, not the annex.
- run 3: correct again.

The foreword is where a document states its relationship to others, which is
exactly what a "which norms apply?" question needs. Removing it did not make
the model say less; it made the model invent a replacement. Pinned by
`tests/test_front_matter.py::test_foreword_is_kept_because_it_states_document_relationships`.

## The core failure is unchanged

Q3, Q4 and Q5 still never retrieve the operative national-annex clause in
any of the three runs. Front-matter removal freed ranking slots but did not
make those clauses reachable, which is the result that matters: the cause is
not competition from noise, it is that the clauses have no retrievable
vocabulary. `§6.1.4` is, in full, *"Festlegung zu ÖNORM EN 1992-1-1:2015,
Abschnitt 3.1.6(1)P — Der empfohlene Wert wird übernommen."*

Q5 did improve in sourcing without becoming correct. It now surfaces the
buildings recommendation it missed at baseline —

> Der landesspezifische Wert α_cc sollte zwischen 0,8 und 1,0 liegen … Der
> empfohlene Wert ist 1,0.

— and then still reaches for `ÖNORM EN 1992-2` (**Brücken**, α_cc = 0,85) and
concludes *"Ja … eine Abminderung … vorgesehen"*. It has both numbers in
front of it and no basis for choosing, because the document that decides —
`ÖNORM B 1992-1-1` §6.1.4 — is still not retrieved.

## What to try next

Two-pass clause retrieval: take the clause numbers out of the first pass
(here `3.1.6`) and run a lexical lookup for them. `§6.1.4` contains the
literal string `3.1.6(1)P`, so it is reachable that way while being
unreachable semantically. This is now the only untested hypothesis that
addresses the measured cause, and it needs no schema change.

A second, cheaper guard worth considering independently: the answer drew on
a different *part* of the Eurocode (1992-2, bridges) for a question with no
bridge context. Part identity is already parsed (`services/norm_identity.py`).
