# Figures — measured, and not a gap

Tables turned out to be a real failure mode, so images looked like the next
one: 2,189 embedded images across the corpus, none read, and Q4's answers
already cite `Bild 6.26` and `Bild 6.27` without being able to see them.

Two approaches were built and compared, as intended — caption-and-label
grouping, and local vision captioning. Then a question was added to measure
them, and the question answered itself.

## The figures are vector, so their labels are already text

Page 121 of `ÖNORM EN 1992-1-1` carries Bild 6.26 and Bild 6.27 as **446
drawing paths and zero embedded images**. Across that document, 77 pages
carry a `Bild N` caption and only 7 hold a raster image; the whole file
contains 18.

The 2,189 figure from `get_images()` was misleading. Detecting captioned
figure regions properly gives **138 in the Austrian corpus** and 174 in the
German one — about a third of the earlier extrapolation, and concentrated
in four raster-heavy documents: `EN 1991-1-4` (412 images), `EN 1993-1-8`
(224), `EN 1991-3` (216), `B 1995-1-1` (185).

Because the figures are vector, their labels are real text and already
indexed — as isolated fragments. What the chunker sees of Bild 6.26 is

    ['1','a','F','Ec0','2','a','3','a','F','FEcd,3','FEcd,1r','F','l',
     'Ed,2','Ed,1','Ed,3']

## Q7 passes without any of it

Q7 was written specifically to need a figure. `Bild 5.4` defines the
effective span graphically and the page carries no prose explaining it —
every text run on it is one of the figure's own labels.

The **baseline** answer, with no figure handling at all:

> l_eff = l_n + a_1 + a_2 … Die Werte a_1 und a_2 … dürfen nach **Bild 5.4**
> bestimmt werden … Für ein nicht durchlaufendes Bauteil:
> **a = min {1/2h; 1/2t}**

Correct formula, correct support case, cites the figure, and the gold page
ranks first. Level 7 before anything was enabled.

The label `a = min {1/2h; 1/2t }` is a single text run in the PDF, so it
survives flattening intact. Grouping it under its caption makes the chunk
tidier; it does not make the answer possible, because the answer already
was.

## The local vision model was worse than useless

`SmolVLM-500M` on MPS, free, ~19 s per figure. On Bild 6.27 — a
compression-tension node with reinforcement — it produced:

> "a **ladder system** … **Ladder Lengths (L1)**: The length of the ladder
> is labeled as **25 meters**"

Fabricated units and dimensions, fluent enough to be indexed and retrieved.
In a tool whose promise is citation accuracy that is worse than silence.
Captioning the corpus would also have taken 5+ hours and required
`torchvision` plus model weights in any environment that ingests.

A paid vision model would do better — estimated at **~$1.40 one-off** for
both corpora at gpt-4o rates, roughly $0.02 per newly uploaded document.
Cost was never the obstacle.

## Decision

**Nothing shipped.** Both implementations were reverted; only Q7 was kept,
because it documents that figure content is already reachable for the
questions this set covers.

Testing first cost one question and about $0.04, instead of an ingest
pipeline, an API dependency and a recurring bill for a mechanism with no
measured benefit.

## What would change this

The only figures whose content is genuinely unreachable are **raster**
ones, and they cluster in the wind, snow and steel-joint documents that no
question in this set touches. A wind-load or steel-connection question
against `EN 1991-1-4` or `EN 1993-1-8` would be a real test. Until someone
asks one, figures are not a demonstrated gap.
