"""Second-pass clause lookup.

A national annex modifies a European clause by referring to it by number
while carrying no domain vocabulary of its own, so it is unreachable by
embedding or BM25. See eval/runs/2026-08-06-front-matter-and-labels.md.
"""

from services.llm import _clause_reference_ids, _leading_clause_numbers


class TestLeadingClauseNumbers:
    def test_reads_the_heading_the_chunker_prepends(self):
        texts = [("3.1.6 Bemessungswert der Betondruckfestigkeit\n(1)P ...", "en")]
        assert _leading_clause_numbers(texts) == [("3.1.6", "en")]

    def test_preserves_rank_order_and_drops_duplicates(self):
        texts = [("6.2 Querkraft ...", "en"), ("3.1.6 Bemessung ...", "en"),
                 ("6.2 Querkraft weiter ...", "en")]
        assert _leading_clause_numbers(texts) == [("6.2", "en"), ("3.1.6", "en")]

    def test_ignores_chunks_without_a_clause_heading(self):
        assert _leading_clause_numbers([("Vorwort\nIm Eurocode ...", "b")]) == []

    def test_requires_a_sub_level_so_a_bare_page_number_is_not_a_clause(self):
        assert _leading_clause_numbers([("12 Konstruktionsregeln", "en")]) == []


class TestClauseReferenceIds:
    ids = ["en_1", "b_1", "b_2", "other_1"]
    docs = {
        "en_1": "3.1.6 Bemessungswert ... fcd = αcc fck / γC",
        "b_1": "6.1.4 Festlegung zu ÖNORM EN 1992-1-1:2015, Abschnitt 3.1.6(1)P\n"
               "Der empfohlene Wert wird übernommen.",
        "b_2": "9.2 Querkraft — Festlegung zu Abschnitt 6.2.3(2)",
        "other_1": "13.1.6 Etwas ganz anderes",
    }
    meta = {
        "en_1": {"document_id": "en"},
        "b_1": {"document_id": "b"},
        "b_2": {"document_id": "b"},
        "other_1": {"document_id": "other"},
    }

    def _find(self, clause, exclude):
        return _clause_reference_ids(clause, exclude, self.ids, self.docs, self.meta)

    def test_finds_the_annex_clause_that_modifies_the_retrieved_one(self):
        # The whole point: this chunk has no domain vocabulary, only "3.1.6".
        assert self._find("3.1.6", {"en"}) == ["b_1"]

    def test_excludes_the_document_the_clause_came_from(self):
        # A norm cites its own clauses constantly; without this the second
        # pass just returns more of the same document.
        assert "en_1" not in self._find("3.1.6", {"en"})

    def test_an_annex_already_in_the_results_is_still_searchable(self):
        # Regression: excluding every document present in the first pass meant
        # one front-matter chunk of ÖNORM B 1992-1-1 ranking barred its own
        # §6.1.4 from the lookup — the clause the whole mechanism targets.
        assert self._find("3.1.6", {"en"}) == ["b_1"]

    def test_does_not_match_a_longer_clause_number(self):
        # 13.1.6 must not satisfy a lookup for 3.1.6.
        assert "other_1" not in self._find("3.1.6", {"en"})

    def test_matches_a_sub_clause_of_the_retrieved_clause(self):
        # A question about §6.2 Querkraft should surface an annex that
        # modifies §6.2.3, which is a national deviation inside that topic.
        # Prefix matching is intended; only a *different* number like 13.1.6
        # must be rejected, which the lookbehind handles.
        assert self._find("6.2", {"en"}) == ["b_2"]

    def test_returns_nothing_when_no_document_modifies_the_clause(self):
        assert self._find("9.9.9", {"en"}) == []


class TestNormFamilyScope:
    def test_family_is_read_from_the_norm_reference(self):
        from services.llm import _norm_family
        assert _norm_family("ÖNORM EN 1992-1-1") == "1992"
        assert _norm_family("ÖNORM B 1992-1-1") == "1992"
        assert _norm_family("DIN EN 1990/NA") == "1990"
        assert _norm_family(None) is None

    def test_a_clause_number_does_not_cross_norm_families(self):
        # Regression: EN 1992-1-1 §9.2.2 (Querkraftbewehrung) matched
        # ÖNORM B 1991-1-3 §9.2.2 (Schneeverwehungen), putting a snow-load
        # clause into a reinforced-concrete shear question.
        ids = ["concrete_annex", "snow_annex"]
        docs = {
            "concrete_annex": "9.2 Festlegung zu ÖNORM EN 1992-1-1, Abschnitt 9.2.2",
            "snow_annex": "9.2.2 Außergewöhnliche Verhältnisse bei Schneeverwehungen",
        }
        meta = {
            "concrete_annex": {"document_id": "b1992", "norm_reference": "ÖNORM B 1992-1-1"},
            "snow_annex": {"document_id": "b1991", "norm_reference": "ÖNORM B 1991-1-3"},
        }
        found = _clause_reference_ids("9.2.2", {"en1992"}, ids, docs, meta, family="1992")
        assert found == ["concrete_annex"]
