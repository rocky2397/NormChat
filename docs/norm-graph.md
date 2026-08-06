# Norm document relationships — findings

Notes from investigating how to tell which uploaded documents belong
together. **Document identity is implemented** (`backend/services/norm_identity.py`).
The relationship layers described further down are **not built**, and this
file is a record of what the corpora showed, not a commitment to build them.

## Why this matters

In the DACH region a Eurocode part alone does not state what applies. The
European norm leaves nationally determined parameters open, and a national
document fills them in:

| | European norm | National document |
| --- | --- | --- |
| Austria | `ÖNORM EN 1992-1-1` | `ÖNORM B 1992-1-1` |
| Germany | `DIN EN 1990` | `DIN EN 1990/NA` |

Both covers say so outright — *"Die ÖNORM EN 1992-1-1 und ÖNORM B 1992-1-1
sind gemeinsam anzuwenden."*

The national document is a **delta**, not a copy. `ÖNORM B 1992-1-1 §6.1.4`
reads, in full: *"Festlegung zu ÖNORM EN 1992-1-1:2015, Abschnitt 3.1.6(1)P
— Der empfohlene Wert wird übernommen."* It carries no domain vocabulary, so
neither BM25 nor the embedding can reach it from a question phrased in words
("Muss die Betondruckfestigkeit … abgemindert werden?", `eval/questions.md`
Q5). Ask that with only the EN uploaded and the answer is confident,
well-cited, and wrong for Austria.

## What is implemented: identity

`parse_identity(filename, first_page_text)` returns a structured
`NormIdentity` — publisher, designation, number, `national_annex`,
amendment, edition, jurisdiction — read from the **cover page**, because
that is the document's own statement of what it is. The filename is a
fallback for scans.

Validated across both corpora (neither is in the repo — norm PDFs are
copyrighted, see `SPEC.md`):

| Corpus | Documents | Resolved | National annexes | Key collisions |
| --- | --- | --- | --- | --- |
| Austria, `Normen/` | 39 | 39 | 19 | 0 |
| Germany, `Normen-2/` | 137 | 137 | 66 | 0 |

It also surfaced 3 byte-identical duplicate files in the German corpus
(`…-1.pdf` double downloads), which now collide on `versioned_key`.

This fixed a live bug: the previous regex resolved `ÖNORM EN 1990` and
`ÖNORM EN 1990/A1` — and `DIN EN 1990`, `DIN EN 1990/NA`,
`DIN EN 1990/NA/A1` — to the same string. Citations could not distinguish a
norm from its national annex.

### Adding a country

`PROFILES` holds one entry per issuing body. Austria and Germany are
implemented; Switzerland (`SN EN` + SIA) is not. Each profile owns its parse
step rather than sharing one regex, because publishers differ structurally,
not just in wording:

- **ÖNORM** prints `ÖNORM` / designation / `Ausgabe: 2015-02-15`. The parse
  requires the edition to follow the designation — that adjacency is what
  separates the document's own identity from `Ersatz für ÖNORM
  B 1992-1-1:2011-12`, a different edition named on the same cover.
- **DIN** prints the designation as a **standalone line** (`DIN EN 1990/NA`)
  with a German month and year at the head of the page. The parse matches a
  whole line and nothing else.

That second rule was learned the hard way. Searching the flattened page for
the longest match made 18 German EN norms resolve to their own national
annex, because an EN cover *mentions* `DIN EN 1991-1-1/NA` — collapsing
exactly the distinction the module exists to draw. References to other
documents live inside prose; a document's own name stands alone.

Anything no profile recognises falls through to the older patterns in
`services/storage.py` and behaves as before.

## Findings that constrain any future linking work

**Documents declare their own relationships**, densely and in fixed
positions. Counts over the 39 Austrian documents:

| Declaration | Meaning | Coverage |
| --- | --- | --- |
| `Ersatz für …` | supersedes an edition | 37/39 |
| `Ident (IDT) mit EN … + AC + A1` | adopts European original | 20/39 |
| `Nationale Festlegungen zu …` | is the national annex to | 16/39 |
| `… sind gemeinsam anzuwenden` | must be applied together | 18/39 |
| `… wird als ÖNORM B … publiziert` | names its own annex | 18/39 |

Plus clause-level links: **232** `Festlegung zu … Abschnitt 3.1.6(1)P`
headings in `B 1992-1-1` alone, 124 in `B 1991-2`, 93 in `B 1991-1-4`.

So links can be read from the documents rather than curated externally. That
suits bring-your-own-PDF, and it cannot go stale the way a maintained
relationship database would.

Four constraints any design must respect:

1. **Many-to-many.** `B 1992-2` declares clause links to both `EN 1992-2`
   and `EN 1992-1-1`. Pairing by document number is not sufficient.
2. **Published norms contain errors.** `B 1993-1-1` references
   `ÖNORM EN 1933-1-1` — a typo for 1993. Resolution must fuzzy-match and
   flag, never silently rewrite and never silently drop.
3. **Text is dirty.** References carry non-breaking spaces
   (`EN\xa01992-1-1`), U+2011 hyphens, line breaks mid-reference, and table
   of contents dot-leaders bleed into clause targets
   (`4.4.1.2(3)......13`). `normalize_reference_text()` exists for this.
4. **More document types than expected.** Beyond norm and national annex
   there are amendments (`/A1`), amendments to annexes (`/NA/A1`), and
   corrigenda (`DIN EN 1991-3 Berichtigung 1`).

## Options not taken

**A relationship graph** — typed edges (`replaces`, `supplements`,
`applied_with`) carrying evidence, plus clause-level links, plus companion
retrieval. Deferred: the failure it fixes is predicted, not measured.
`eval/questions.md` still has TBD expected sources and has never been run.

**Two-pass retrieval** — the cheaper test of the same hypothesis. Take
clause numbers out of the first pass, then run a lexical lookup for them;
that reaches `B §6.1.4` because its text literally contains `3.1.6(1)P`. No
identity model, no schema change, roughly 20 lines. Worth trying before
anything larger.

**Blocker if a graph is ever built:** document-level relations want a
`document_relations` table, and `CLAUDE.md` forbids schema changes. That is
a decision for a human owner, not something to work around by duplicating
per-document edges onto every chunk.

## Recommended next step

Fill in the expected sources in `eval/questions.md` and run the five
questions, so the next retrieval decision rests on a measurement rather than
a prediction.
