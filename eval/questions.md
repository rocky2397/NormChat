# Evaluation question set

The reference questions used to judge whether a change to retrieval,
chunking, or citation logic actually helped. `.claude/prioritization.md`
requires that any ticket touching retrieval quality states an evaluation
method — this file is that method.

These are real questions from a practising Austrian structural engineer,
not synthetic ones. All five are Austria-specific, and four explicitly ask
for national annexes ("samt nationaler Erläuterungen und Ergänzungen").
That is deliberate: the capability under test is surfacing a **ÖNORM EN
clause together with its ÖNORM B national modification**, rather than
answering plausibly from the EN alone. An answer that cites only the EN
where a B-supplement applies is wrong, even when it reads well.

## Corpus

Questions assume one project containing the ÖNORM PDFs below. Norm
documents are copyrighted and are never committed to this repo (see
"Bring-your-own-PDF" in `SPEC.md`) — this records *what to load*, not the
documents themselves. Locally these live under `example_data/Normen/`,
which is gitignored.

Directly exercised:

| Question | Files |
| --- | --- |
| Q1, Q2 | `OENORM_EN_1995-1-2_2011_09_01_de.pdf`, `OENORM_B_1995-1-2_2011_09_01_de.pdf` |
| Q3, Q4, Q5 | `OENORM_EN_1992-1-1_2015_02_15_DE.pdf`, `OENORM_B_1992-1-1_2018_01_01_de.pdf` |

Load the **full set** (EN 1990, 1991, 1992, 1993, 1995, 1997 — EN and B
variants, 39 files) rather than only the four above. The remaining files
are the discriminators: with the whole corpus present, retrieval has to
distinguish `EN 1992-1-1` from `B 1992-1-1`, which share clause numbering
and vocabulary. Testing against a narrow corpus hides exactly the failure
mode these questions exist to catch.

## How to run

1. Create a project, upload the corpus, wait for ingestion to finish.
2. Ask each question below in order, in a fresh chat.
3. For each, record the three checks in the table under that question.
4. Score `gut` / `mittel` / `schlecht` — the same scale the in-app
   feedback widget uses, so manual runs and tester feedback speak one
   language.

### The three checks

1. **National annex** — is a **substantive clause** of the ÖNORM B document
   cited? A cover, foreword or contents page does **not** count. This
   distinction is the whole point: an early run cited
   `ÖNORM B 1992-1-1, S. 4` — the Vorwort — which looked like the annex had
   been consulted while carrying no rule at all.
2. **Clause** — is the cited clause the right one? Compare against
   *Expected sources* below.
3. **Highlight** — clicking the source card opens the right page *and* the
   highlight lands on the sentence the answer relied on.

### Grading

Apply in order; the first one that matches wins.

- **`schlecht`** — any of:
  - a factual error, or a value taken from a norm that does not govern the
    case asked about;
  - a claim the answer does not source — asserting that national provisions
    apply without citing one is worse than admitting they were not found,
    because it cannot be checked;
  - no substantive annex clause where the question needs one (see per-question
    criteria below).
- **`mittel`** — everything asserted is correct and sourced, but the answer
  is materially incomplete: it misses a step, a value or a clause the
  question asked for, and says so or simply stops short.
- **`gut`** — complete and fully sourced, and the highlight lands on the
  passage the answer relied on. A right page with a highlight on the wrong
  paragraph is `mittel`, not `gut`.

Record separately, since they are defects rather than grades:

- **label leak** — any `[Quelle N]` / `(siehe Quelle N)` reaching the user.
- **garbled formula** — symbols dropped or mangled in a reproduced equation.

### The eight levels

Each level is a mode observed in an actual run, ordered by how far it would
mislead a practising engineer. The three-value scale maps onto it: 1–4 are
`schlecht`, 5–6 `mittel`, 7–8 `gut`.

1. **Wrong rule applied** — the answer gives a value or rule from a norm that
   does not govern the case asked about, presented as though it did.
2. **Wrong about the norms** — the answer mischaracterises a document or the
   relationship between two of them.
3. **Hollow citation** — the annex is cited, but only its cover, foreword or
   contents page, so the source card implies a check that never happened.
4. **Unsourced claim** — the answer states that national provisions apply
   without citing anything at all for them.
5. **Honestly incomplete** — everything asserted is correct and sourced, but
   a step, value or clause the question asked for is missing.
6. **Complete but indirectly sourced** — the answer is right and fully
   supported, yet cited from a summary or overview table rather than the
   operative clause.
7. **Clause-accurate, weak locate** — the right clauses are cited, but the
   highlight is missing or lands on the wrong passage in the PDF.
8. **Fully verifiable** — complete, cited at clause level, and the highlight
   lands on the sentence the answer relied on.

Levels 1 and 2 are errors, 3 and 4 are unverifiable claims, 5 and 6 are
honest shortfalls, 7 and 8 differ only in whether the reader can find the
passage without hunting.

### Why grades are not averaged

An unsourced claim is not half of a good answer. The grade is the worst
finding, not the mean of the checks — a tool that is right about the EN and
invents the national part is more dangerous than one that is simply
incomplete, because the reader has no way to tell.

Record the run (date, commit, scores, notes) somewhere durable when
evaluating a change — a diff between two runs is the point.

## Expected sources

**Status: proposed, awaiting engineering sign-off.**

The clauses below were located mechanically — searched for in the actual
PDFs and confirmed to exist at the stated page — but *whether they are the
right answer* is an engineering judgement that has not been made. Only Q5 is
fully verified end to end (the clause text was read and cross-checked
against the rendered page). Treat the rest as candidates: confirm or correct
them once, from the documents, and they hold for every later run.

Nothing here was written from memory. Where a question plausibly needs more
sources than are listed, that is noted rather than guessed at.

**Page numbers are PDF page indices**, which is what NormChat cites and what
a source card shows. They differ from the printed page number in the
document — EN 1992-1-1 §3.1.6 is PDF page 36, printed page 34.

Each question below also carries a **gold block** — a fenced code block
tagged `gold`, read by `backend/eval/retrieval_probe.py` for headless
per-stage rank reporting. Each line is `norm_reference: page[, page ...]`,
with pages as PDF page indices as defined above; a retrieved chunk counts
as a hit when its `norm_reference` metadata matches and its `page_number`
is in the page set. Writing `*` instead of pages makes the label
document-level — any chunk of that document counts. Use it only where the
question really is about which documents apply rather than which clause
does, as in Q1; elsewhere it would hide the distinction the set exists to
measure. A block containing only `TBD` means the labels have
not been signed off, and the probe skips that question. Labels are
`(norm_reference, page)` pairs rather than chunk ids, because Chroma ids
embed a per-ingestion document id and would not survive a re-ingest.

---

## Q1

> Welche Normen sind in Österreich für das Thema Holzbau (Bemessung im
> Brandfall) zu berücksichtigen?

- **Family:** EN 1995 (Holzbau, Brandfall)
- **Probes:** multi-document coverage. The answer must name both
  `ÖNORM EN 1995-1-2` and `ÖNORM B 1995-1-2`. Naming only one is a fail
  regardless of how well-written the answer is.
- **Expected sources:** _proposed_
  - `ÖNORM EN 1995-1-2` (document-level — the answer must name it)
  - `ÖNORM B 1995-1-2` (document-level — naming only the EN is a fail)
  - Open question for review: should `ÖNORM EN 1991-1-2` (Einwirkungen im
    Brandfall) and the `1995-1-1` pair count as expected here, or is the
    question strictly about the fire parts?

Gold block — document-level, because the question is: it asks which norms
apply, so the expectation is that a chunk of each document reaches the
context, not that a particular clause does. `*` means any page.

**Still unconfirmed** in the sense that the open question above — whether
`EN 1991-1-2` and the `1995-1-1` pair also belong here — has not been
settled. The two listed are the ones the question cannot be answered
without.

```gold
ÖNORM EN 1995-1-2: *
ÖNORM B 1995-1-2: *
```

- **Grading:**
  - `gut` — names both `ÖNORM EN 1995-1-2` and `ÖNORM B 1995-1-2`, and
    describes the B document as the national supplement to be applied
    *together with* the EN.
  - `mittel` — names both but does not say how they relate, or omits a
    genuinely relevant further norm.
  - `schlecht` — names only one of the pair, or mischaracterises the B
    document. A run once called it *"die konsolidierte Fassung von ÖNORM
    EN 1995-1-2"*, which describes the EN document instead: that is a
    factual error, not an omission.
  - Annex check: a document-level answer, so naming the B document is
    enough here — this is the one question where front matter is a
    legitimate source.

## Q2

> Beschreibe die Schritt-für-Schritt-Vorgehensweise für die Bemessung von
> Holzbauteilen im Brandfall (Feuerwiderstandsklasse R60) in Österreich
> unter Berücksichtigung der aktuellen Normen samt nationaler
> Erläuterungen und Ergänzungen.

- **Family:** EN 1995 (Holzbau, Brandfall)
- **Probes:** multi-hop synthesis across EN + B for a concrete fire
  resistance class. Needs several chunks from more than one document held
  together in one coherent procedure — the case `top_k_chunks = 10`
  exists for.
- **Expected sources:** _proposed_
  - `ÖNORM EN 1995-1-2` §3.4.2 Ungeschützte Oberflächen während der gesamten
    Branddauer — p. 25
  - `ÖNORM EN 1995-1-2` §4.2.2 Methode mit reduziertem Querschnitt — p. 35
  - `ÖNORM EN 1995-1-2` §4.2.3 Methode mit reduzierten Eigenschaften — p. 36
  - `ÖNORM B 1995-1-2` §6.1 Abbrandtiefe — p. 7
  - Open question for review: which of the two design methods (4.2.2 / 4.2.3)
    the answer should lead with for R60, and whether the load-combination
    clauses in B 1995-1-2 §5 belong in the expected set.

Gold block — the pages of the expected sources above: `EN 1995-1-2` §3.4.2
*Ungeschützte Oberflächen* (p. 25), §4.2.2 *Methode mit reduziertem
Querschnitt* (p. 35), §4.2.3 *Methode mit reduzierten Eigenschaften*
(p. 36), and `B 1995-1-2` §6.1 *Abbrandtiefe* (p. 7).

**Still unconfirmed.** These headings were located in the documents, but
whether they are the *right* answer for R60 is an engineering judgement
nobody has made. Filled in anyway because leaving it `TBD` made the probe
skip Q2 — and Q2 is the question query expansion (#11) was built for, so
its A/B was measured on every question except its own target.

```gold
ÖNORM EN 1995-1-2: 25, 35, 36
ÖNORM B 1995-1-2: 7
```

- **Grading:**
  - `gut` — gives the charring-based procedure (`Abbrandtiefe`, reduced
    cross-section) with the Austrian values, citing `EN 1995-1-2` §3.4.x /
    §4.2.x and `B 1995-1-2` §6.1.
  - `mittel` — a correct but generic fire-design procedure that never
    reaches charring or the reduced cross-section, which is the method the
    question is actually about.
  - `schlecht` — cites the same generic clause for every step as though it
    were the answer, or gives R60 values it cannot source.

## Q3

> Erläutere mir die Querkraftbemessung eines Stahlbetonbalkens in
> Österreich unter Berücksichtigung der aktuellen Normung.

- **Family:** EN 1992-1-1 (Stahlbeton, Querkraft)
- **Probes:** clause-level precision on a single well-defined topic. The
  simplest of the five — if this one regresses, something is broadly
  broken rather than subtly wrong.
- **Expected sources:** _proposed_
  - `ÖNORM EN 1992-1-1` §6.2 Querkraft — p. 93
  - `ÖNORM B 1992-1-1` §9.2 Querkraft — p. 21

Gold block — p. 93 is the §6.2 heading from the expected sources above;
p. 97–98 are where run 8 located the §6.2.3 truss-model clauses it graded
as the right EN citation (`eval/runs/2026-08-06-current.md`):

```gold
ÖNORM EN 1992-1-1: 93, 97, 98
ÖNORM B 1992-1-1: 21
```

- **Grading:**
  - `gut` — the truss model from `EN 1992-1-1` §6.2.3 *and* the Austrian
    provisions from `B 1992-1-1` §9.2, with the formulae intact.
  - `mittel` — the EN design clause is right and the answer stops there,
    without claiming anything about national provisions.
  - `schlecht` — states that national provisions apply while citing only the
    B document's front matter. The question says "in Österreich" and
    "aktuelle Normung", so what applies in Austria is EN **and** B; an
    unsupported claim about the national part is the failure this question
    exists to catch.

## Q4

> Führe mich Schritt für Schritt durch die Knotenbemessung im
> Stahlbetonbau für einen Druck-Zug-Knoten in Österreich unter
> Berücksichtigung der aktuellen Normen samt nationaler Erläuterungen und
> Ergänzungen.

- **Family:** EN 1992-1-1 (Stahlbeton, Knoten / Stabwerkmodell)
- **Probes:** the deepest retrieval target in the set — a specific node
  type within strut-and-tie design. Tests whether a narrow clause is
  reachable when the corpus contains many superficially similar
  Stahlbeton passages.
- **Expected sources:** _proposed_
  - `ÖNORM EN 1992-1-1` §6.5.4 Bemessung der Knoten — p. 120
  - `ÖNORM B 1992-1-1` §9.5 Stabwerkmodelle — p. 28

Gold block:

```gold
ÖNORM EN 1992-1-1: 120
ÖNORM B 1992-1-1: 28
```

- **Grading:**
  - `gut` — the §6.5.4 procedure with the k-values **as set for Austria** in
    `B 1992-1-1` §9.5.
  - `mittel` — the §6.5.4 procedure with the EN *recommended* k-values,
    explicitly flagged as the recommended values with the national annex not
    found. Honest and incomplete.
  - `schlecht` — presents the EN recommended values as if they were the
    Austrian ones, or claims the national supplement was applied without
    citing a clause of it.

## Q5

> Muss die Betondruckfestigkeit zur Berücksichtigung der
> Langzeitauswirkungen in Österreich abgemindert werden? Prüfe die
> aktuelle Normung samt nationaler Ergänzungen.

- **Family:** EN 1992-1-1 (Betondruckfestigkeit, Langzeitauswirkungen)
- **Probes:** a yes/no where the Austrian national annex governs. The
  answer hinges on the ÖNORM B value, so answering from the EN
  recommendation alone produces a confident wrong answer — the single
  most valuable question in the set.
- **Also exercises:** formula rendering in the answer, since the response
  carries the design-strength expression (see the LaTeX rules in
  `SYSTEM_PROMPT`, `backend/services/llm.py`, and the delimiter rewriting
  in `frontend/src/components/AnswerText.jsx`).
- **Expected sources:** _verified_
  - `ÖNORM EN 1992-1-1` §3.1.6(1)P — p. 36. Defines
    \(f_{cd} = \alpha_{cc} f_{ck} / \gamma_C\); α_cc is the coefficient for
    long-term effects on compressive strength.
  - `ÖNORM B 1992-1-1` §6.1.4 — p. 12. The Austrian decision, in full:
    *"Festlegung zu ÖNORM EN 1992-1-1:2015, Abschnitt 3.1.6(1)P — Der
    empfohlene Wert wird übernommen."*
  - An answer citing only the EN has not answered the question, which asks
    explicitly about national supplements.

Gold block:

```gold
ÖNORM EN 1992-1-1: 36
ÖNORM B 1992-1-1: 12
```

- **Grading:**
  - `gut` — states both recommended values with the part each comes from
    (`EN 1992-1-1` → 1,0; `EN 1992-2` → 0,85), the Austrian decision from
    `B 1992-1-1`, and a conclusion that follows from them.
  - `mittel` — gives the buildings value and the Austrian decision but does
    not surface the conflicting bridge value, so the reader cannot see what
    was set aside.
  - `schlecht` — answers with 0,85 from `ÖNORM EN 1992-2`. That is the
    **bridge** part; applying it to a general question is a value taken from
    a norm that does not govern the case. The baseline run did exactly this,
    with a confident "Ja".

## Q6

> Welche Mindestbetondeckung c_min,dur ist in Österreich für Betonstahl in der
> Expositionsklasse XC4 anzusetzen? Prüfe die aktuelle Normung samt
> nationaler Ergänzungen.

- **Family:** EN 1992-1-1 (Dauerhaftigkeit, Betondeckung)
- **Probes:** whether an answer that lives in a **table cell** can be reached
  at all. The other five questions are answered by prose clauses; this one
  is not. `c_min,dur` is given per exposure class in a grid, and the
  extractor flattens grids into a bare column of values — row and column
  association survive only as reading order, so the model must reconstruct
  which number belongs to XC4.
- **Added by Claude, not by the engineer who wrote Q1–Q5.** It exists to
  measure a known pipeline gap (see the images/tables note below), and the
  question itself has not been reviewed for whether it is one an engineer
  would actually ask.
- **Expected sources:** _proposed_
  - `ÖNORM EN 1992-1-1` — the `c_min,dur` tables, pp. 56–57
  - `ÖNORM B 1992-1-1` §7.1–7.7 Dauerhaftigkeit und Betondeckung — pp. 13–14
- **The numeric answer is deliberately not stated here.** Reading it off the
  grid requires knowing which Anforderungsklasse applies, which is an
  engineering judgement; recording a value nobody has confirmed would put
  unverified ground truth into the one file that is supposed to catch it.
- **Grading:**
  - `gut` — names the correct `c_min,dur` for XC4 with the Anforderungsklasse
    it assumed, cites the EN table, and reflects the Austrian provisions in
    `B 1992-1-1` §7.
  - `mittel` — reaches the table and the national clauses but will not commit
    to a value, or states the value without saying which class it assumed.
  - `schlecht` — gives a number that is not in the table, silently picks a
    class, or claims national provisions without citing one.

Gold block — the pages carrying the tables and the national provisions.
Document-level would be too coarse here: the point is whether the *table
page* is reached.

```gold
ÖNORM EN 1992-1-1: 56, 57
ÖNORM B 1992-1-1: 13, 14
```

## Q7

> Wie wird die effektive Stützweite l_eff eines Stahlbetonbalkens bestimmt,
> und wie ist das Auflagermaß a_i bei einem nicht durchlaufenden Bauteil
> anzusetzen?

- **Family:** EN 1992-1-1 (Schnittgrößenermittlung, effektive Stützweite)
- **Probes:** whether an answer carried by a **figure** can be reached.
  `Bild 5.4` defines l_eff for each support condition graphically, and the
  page carries no prose explaining it — everything the page contains is the
  figure's own labels: `a_i = min {1/2h; 1/2t}`, `(a) nicht durchlaufende
  Bauteile`, `(b) durchlaufende Bauteile`, `(e) Kragarm`. Those labels are
  real text and already indexed, but as isolated fragments with no
  connection to the caption that names them.
- **Added by Claude, not by the engineer who wrote Q1–Q5.** Like Q6 it
  exists to measure a known pipeline gap, and has not been reviewed for
  whether it is a question an engineer would actually ask.
- **Expected sources:** _proposed_
  - `ÖNORM EN 1992-1-1` — `Bild 5.4` and the surrounding §5.3.2.2, p. 66
- **No Austrian annex is expected.** `ÖNORM B 1992-1-1` contains **no
  figures at all**, so unlike Q1–Q6 this question does not test the EN/B
  pairing. That is deliberate: it isolates the figure question from the
  national-annex question the rest of the set already covers.
- **Grading:**
  - `gut` — states l_eff = l_n + a_1 + a_2 with a_i taken from the figure
    (`min {1/2h; 1/2t}` for a non-continuous member) and cites `Bild 5.4`.
  - `mittel` — reaches the clause and the figure but will not commit to how
    a_i is determined, or gives it without saying which support case.
  - `schlecht` — invents a value or rule for a_i, or attributes it to a
    clause that does not carry it.

Gold block — the figure page.

```gold
ÖNORM EN 1992-1-1: 66
```

---

## Known limitation of this set

Every question asks about "die aktuelle Normung". The system has no
concept of currency — it answers from whatever PDFs were uploaded and
cannot tell that an edition has been superseded. A perfect score here
means "correctly answered from the loaded corpus", not "up to date".
Keeping the corpus current is the operator's job, not the tool's.
