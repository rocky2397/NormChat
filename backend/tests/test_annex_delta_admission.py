"""Re-admitting national-annex delta clauses the cross-encoder discards.

A delta states its rule as a reference to the parent it modifies, so a
passage-ranking cross-encoder has nothing to score it on. Measured: the
clause reaches fused rank 3 and is still dropped, and a model 4.8x larger
does the same.

Admission is conditional on the parent being retrieved. Without that
condition a question about which timber fire norms apply came back citing
ÖNORM B 1995-1-1 — a sibling annex whose parent was never retrieved — while
failing to name B 1995-1-2, the annex the question was about.
"""

from services.llm import (
    ANNEX_DELTA_ADMIT_LIMIT,
    ANNEX_DELTA_FUSED_DEPTH,
    _admit_annex_deltas,
)

DELTA = (
    "6.1.4 Festlegung zu ÖNORM EN 1992-1-1:2015, Abschnitt 3.1.6(1)P\n"
    "Der empfohlene Wert wird übernommen."
)
SIBLING_DELTA = (
    "9.1 Festlegung zu ÖNORM EN 1995-1-1:2019, Abschnitt 6.1.7\n"
    "Der empfohlene Wert wird übernommen."
)
PARENT = "3.1.6 Bemessungswert der Betondruck- und Betonzugfestigkeit\n(1)P ..."
UNRELATED = "7.4.2 Nachweis der Begrenzung der Verformungen"


def _delta(raw: str = DELTA, reference: str = "ÖNORM B 1992-1-1") -> dict:
    # reference_resolution.py records raw_text only where it actually
    # resolved a reference, which is what marks a chunk as a delta.
    return {"norm_reference": reference, "raw_text": raw}


def _plain(reference: str = "ÖNORM EN 1992-1-1") -> dict:
    return {"norm_reference": reference}


class TestAdmitAnnexDeltas:
    def test_readmits_a_delta_whose_parent_clause_was_retrieved(self):
        docs = {"parent": PARENT, "delta": DELTA}
        meta = {"parent": _plain(), "delta": _delta()}
        assert _admit_annex_deltas(["parent"], ["delta", "parent"], docs, meta) == [
            "parent",
            "delta",
        ]

    def test_rejects_a_delta_whose_parent_was_not_retrieved(self):
        # The regression this condition exists for: a sibling annex riding in
        # on nothing, and crowding out the annex actually asked about.
        docs = {"parent": PARENT, "sibling": SIBLING_DELTA}
        meta = {"parent": _plain(), "sibling": _delta(SIBLING_DELTA, "ÖNORM B 1995-1-1")}
        assert _admit_annex_deltas(["parent"], ["sibling", "parent"], docs, meta) == [
            "parent"
        ]

    def test_parent_clause_matches_by_prefix_in_both_directions(self):
        # The delta addresses 3.1.6(1)P while the retrieved parent chunk is
        # headed 3.1.6 — and the reverse also counts.
        docs = {"parent": "3.1.6.2 Unterabschnitt", "delta": DELTA}
        meta = {"parent": _plain(), "delta": _delta()}
        assert "delta" in _admit_annex_deltas(["parent"], ["delta"], docs, meta)

    def test_right_clause_number_in_the_wrong_norm_is_not_a_parent(self):
        docs = {"other": PARENT, "delta": DELTA}
        meta = {"other": _plain("ÖNORM EN 1995-1-2"), "delta": _delta()}
        assert _admit_annex_deltas(["other"], ["delta", "other"], docs, meta) == ["other"]

    def test_unrelated_parent_clause_does_not_admit(self):
        docs = {"parent": UNRELATED, "delta": DELTA}
        meta = {"parent": _plain(), "delta": _delta()}
        assert _admit_annex_deltas(["parent"], ["delta"], docs, meta) == ["parent"]

    def test_does_not_duplicate_a_delta_the_reranker_kept(self):
        docs = {"parent": PARENT, "delta": DELTA}
        meta = {"parent": _plain(), "delta": _delta()}
        assert _admit_annex_deltas(["delta", "parent"], ["delta"], docs, meta) == [
            "delta",
            "parent",
        ]

    def test_ignores_deltas_the_fusion_ranked_deep(self):
        deep = ANNEX_DELTA_FUSED_DEPTH + 5
        fused = [f"filler{i}" for i in range(deep)] + ["delta"]
        docs = {cid: UNRELATED for cid in fused} | {"parent": PARENT, "delta": DELTA}
        meta = {cid: _plain() for cid in fused} | {"parent": _plain(), "delta": _delta()}
        assert _admit_annex_deltas(["parent"], fused, docs, meta) == ["parent"]

    def test_admission_is_capped(self):
        fused = [f"delta{i}" for i in range(ANNEX_DELTA_ADMIT_LIMIT + 3)]
        docs = {cid: DELTA for cid in fused} | {"parent": PARENT}
        meta = {cid: _delta() for cid in fused} | {"parent": _plain()}
        admitted = _admit_annex_deltas(["parent"], fused, docs, meta)
        assert len(admitted) == 1 + ANNEX_DELTA_ADMIT_LIMIT

    def test_unenriched_project_is_untouched(self):
        # No chunk carries raw_text before enrichment has run, so the whole
        # mechanism must be inert rather than guessing.
        fused = [f"c{i}" for i in range(10)]
        docs = {cid: UNRELATED for cid in fused}
        meta = {cid: _plain() for cid in fused}
        assert _admit_annex_deltas(["c0", "c1"], fused, docs, meta) == ["c0", "c1"]

    def test_preserves_reranked_order_and_appends(self):
        # Reranked order is the reranker's judgement and must survive; the
        # delta is added to it, not merged into it.
        docs = {"parent": PARENT, "b": UNRELATED, "delta": DELTA}
        meta = {"parent": _plain(), "b": _plain(), "delta": _delta()}
        assert _admit_annex_deltas(["b", "parent"], ["delta"], docs, meta) == [
            "b",
            "parent",
            "delta",
        ]
