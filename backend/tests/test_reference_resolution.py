"""Index-time reference resolution for national-annex delta clauses.

A delta clause addresses its parent by number and carries no domain
vocabulary of its own, so neither the embedding nor BM25 can reach it from a
question phrased in words. The enrichment pass appends the heading text of
the parent clause to the *indexed* representation only; what is shown, sent
to the LLM and grounded for highlighting must stay the original chunk text.
"""

import logging

import pytest

import services.llm as llm_module
import services.reference_resolution as reference_resolution
from services.llm import _ground_excerpt, retrieve_sources
from services.reference_resolution import (
    ClauseReference,
    _reference_matches_document,
    enrich_project_references,
    extract_clause_references,
)

EN_HEADING = "3.1.6 Bemessungswerte der Betondruck- und Betonzugfestigkeit"
EN_CHUNK = (
    EN_HEADING
    + "\n(1)P Der Bemessungswert der Betondruckfestigkeit wird mit alpha_cc bestimmt."
)
B_CHUNK = (
    "6.1.4 Festlegung zu ÖNORM EN 1992-1-1:2015, Abschnitt 3.1.6(1)P\n"
    "Der empfohlene Wert wird übernommen."
)
SNOW_CHUNK = (
    "9.2.2 Außergewöhnliche Verhältnisse bei Schneeverwehungen\n"
    "Für Schneeverwehungen gelten besondere Lastannahmen."
)


class FakeCollection:
    def __init__(self):
        self.ids = []
        self.documents = {}
        self.metadatas = {}
        self.vectors = {}

    def add(self, ids, embeddings, documents, metadatas):
        for cid, vector, text, meta in zip(ids, embeddings, documents, metadatas):
            self.ids.append(cid)
            self.vectors[cid] = vector
            self.documents[cid] = text
            self.metadatas[cid] = meta

    def update(self, ids, embeddings, documents, metadatas):
        for cid, vector, text, meta in zip(ids, embeddings, documents, metadatas):
            self.vectors[cid] = vector
            self.documents[cid] = text
            self.metadatas[cid] = meta

    def get(self, include=None, where=None):
        return {
            "ids": list(self.ids),
            "documents": [self.documents[cid] for cid in self.ids],
            "metadatas": [self.metadatas[cid] for cid in self.ids],
        }

    def count(self):
        return len(self.ids)

    def query(self, query_embeddings=None, n_results=10, include=None):
        return {"ids": [self.ids[:n_results]]}


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[float(len(text)), 1.0] for text in texts]

    def embed_query(self, text):
        return [1.0, 1.0]


def _meta(document_id, norm_reference):
    return {
        "document_id": document_id,
        "page_number": 1,
        "chunk_index": 0,
        "source_filename": document_id + ".pdf",
        "norm_reference": norm_reference,
        "edition": "",
    }


def _add(collection, document_id, norm_reference, texts):
    for index, text in enumerate(texts):
        collection.add(
            ids=[f"{document_id}_{index}"],
            embeddings=[[0.0, 0.0]],
            documents=[text],
            metadatas=[dict(_meta(document_id, norm_reference), chunk_index=index)],
        )


@pytest.fixture()
def fake_project(monkeypatch):
    collection = FakeCollection()
    monkeypatch.setattr(reference_resolution, "get_collection", lambda project_id: collection)
    monkeypatch.setattr(reference_resolution, "get_embeddings", lambda: FakeEmbeddings())
    return collection


class TestExtractClauseReferences:
    def test_reads_the_canonical_annex_reference(self):
        assert extract_clause_references(B_CHUNK) == [
            ClauseReference(series="EN", number="1992-1-1", clause="3.1.6")
        ]

    def test_normalizes_nbsp_u2011_hyphens_and_mid_reference_line_breaks(self):
        # Typeset references carry non-breaking spaces (U+00A0), U+2011
        # hyphens and wrap across lines mid-reference; all must compare
        # equal to the plain form.
        nbsp = chr(160)
        nb_hyphen = chr(8209)
        text = (
            "Festlegung zu ÖNORM\nEN" + nbsp + "1992" + nb_hyphen + "1"
            + nb_hyphen + "1:2015, Abschnitt 3.1.6(1)P"
        )
        assert extract_clause_references(text) == [
            ClauseReference(series="EN", number="1992-1-1", clause="3.1.6")
        ]

    def test_contents_page_dot_leaders_do_not_bleed_into_the_clause(self):
        text = "ÖNORM EN 1990:2013, Abschnitt 4.4.1.2(3)......13"
        assert extract_clause_references(text) == [
            ClauseReference(series="EN", number="1990", clause="4.4.1.2")
        ]

    def test_a_reference_without_a_named_norm_is_not_extracted(self):
        # "Festlegung zu Abschnitt 6.2.3(2)" does not name its norm; with
        # several documents sharing the clause number there is nothing
        # deterministic to resolve against.
        assert extract_clause_references("Festlegung zu Abschnitt 6.2.3(2)") == []

    def test_a_top_level_section_reference_is_not_extracted(self):
        # Only sub-level clauses ever become chunk headings, so there is
        # nothing a bare section number could resolve to.
        assert extract_clause_references("ÖNORM EN 1990, Abschnitt 7") == []

    def test_duplicate_references_are_reported_once(self):
        assert len(extract_clause_references(B_CHUNK + "\n" + B_CHUNK)) == 1


class TestReferenceMatchesDocument:
    ref = ClauseReference(series="EN", number="1992-1-1", clause="9.2.2")

    def test_matches_the_referenced_norm_itself(self):
        assert _reference_matches_document(self.ref, "ÖNORM EN 1992-1-1")

    def test_does_not_match_a_different_family(self):
        # EN 1992-1-1 §9.2.2 (Querkraftbewehrung) must not resolve against
        # B 1991-1-3 §9.2.2 (Schneeverwehungen) — clause numbers only mean
        # something inside one norm family.
        assert not _reference_matches_document(self.ref, "ÖNORM B 1991-1-3")

    def test_does_not_match_the_annex_of_the_same_family(self):
        # B 1992-2 declares clause links to both EN 1992-2 and EN 1992-1-1,
        # so pairing by number alone is insufficient; the full designation
        # decides.
        assert not _reference_matches_document(self.ref, "ÖNORM B 1992-1-1")

    def test_a_shorter_part_does_not_match_inside_a_longer_one(self):
        ref = ClauseReference(series="EN", number="1992-1", clause="4.2.1")
        assert not _reference_matches_document(ref, "ÖNORM EN 1992-1-1")

    def test_the_parent_norm_does_not_match_its_national_annex_document(self):
        ref = ClauseReference(series="EN", number="1990", clause="6.4.3")
        assert not _reference_matches_document(ref, "DIN EN 1990/NA")
        assert _reference_matches_document(ref, "DIN EN 1990")

    def test_no_reference_recorded_for_the_document(self):
        assert not _reference_matches_document(self.ref, None)
        assert not _reference_matches_document(self.ref, "")


class TestEnrichment:
    def test_delta_clause_is_indexed_with_the_parent_clause_heading(self, fake_project):
        _add(fake_project, "en", "ÖNORM EN 1992-1-1", [EN_CHUNK])
        _add(fake_project, "b", "ÖNORM B 1992-1-1", [B_CHUNK])

        assert enrich_project_references("p") == 1

        assert fake_project.documents["b_0"] == B_CHUNK + "\n" + EN_HEADING
        assert fake_project.metadatas["b_0"]["raw_text"] == B_CHUNK

    def test_only_changed_chunks_are_re_embedded(self, fake_project):
        _add(fake_project, "en", "ÖNORM EN 1992-1-1", [EN_CHUNK])
        _add(fake_project, "b", "ÖNORM B 1992-1-1", [B_CHUNK])

        enrich_project_references("p")

        assert fake_project.documents["en_0"] == EN_CHUNK
        assert "raw_text" not in fake_project.metadatas["en_0"]
        assert fake_project.vectors["en_0"] == [0.0, 0.0]
        assert fake_project.vectors["b_0"] != [0.0, 0.0]

    def test_enrichment_is_idempotent(self, fake_project):
        _add(fake_project, "en", "ÖNORM EN 1992-1-1", [EN_CHUNK])
        _add(fake_project, "b", "ÖNORM B 1992-1-1", [B_CHUNK])

        assert enrich_project_references("p") == 1
        assert enrich_project_references("p") == 0

        assert fake_project.documents["b_0"] == B_CHUNK + "\n" + EN_HEADING

    def test_annex_uploaded_first_is_enriched_once_the_parent_arrives(
        self, fake_project, caplog
    ):
        _add(fake_project, "b", "ÖNORM B 1992-1-1", [B_CHUNK])
        with caplog.at_level(logging.WARNING):
            assert enrich_project_references("p") == 0
        assert fake_project.documents["b_0"] == B_CHUNK
        assert "EN 1992-1-1" in caplog.text

        _add(fake_project, "en", "ÖNORM EN 1992-1-1", [EN_CHUNK])
        assert enrich_project_references("p") == 1
        assert fake_project.documents["b_0"] == B_CHUNK + "\n" + EN_HEADING

    def test_upload_order_produces_the_same_index(self, monkeypatch):
        # Documents arrive in any order; running the pass after each
        # ingestion must converge to the same enriched index either way.
        def build(order):
            collection = FakeCollection()
            monkeypatch.setattr(
                reference_resolution, "get_collection", lambda project_id: collection
            )
            monkeypatch.setattr(
                reference_resolution, "get_embeddings", lambda: FakeEmbeddings()
            )
            for document_id, norm_reference, texts in order:
                _add(collection, document_id, norm_reference, texts)
                enrich_project_references("p")
            return collection

        en = ("en", "ÖNORM EN 1992-1-1", [EN_CHUNK])
        annex = ("b", "ÖNORM B 1992-1-1", [B_CHUNK])
        en_first = build([en, annex])
        annex_first = build([annex, en])

        assert en_first.documents == annex_first.documents
        raw = lambda c: sorted(
            (cid, meta.get("raw_text")) for cid, meta in c.metadatas.items()
        )
        assert raw(en_first) == raw(annex_first)

    def test_a_clause_number_does_not_cross_norm_families(self, fake_project, caplog):
        # EN 1992-1-1 §9.2.2 must not resolve against B 1991-1-3 §9.2.2:
        # without the designation scope a snow-load heading would be
        # attached to a shear clause.
        citing = "9.2 Festlegung zu ÖNORM EN 1992-1-1, Abschnitt 9.2.2\nQuerkraft."
        _add(fake_project, "b1992", "ÖNORM B 1992-1-1", [citing])
        _add(fake_project, "snow", "ÖNORM B 1991-1-3", [SNOW_CHUNK])

        with caplog.at_level(logging.WARNING):
            assert enrich_project_references("p") == 0

        assert fake_project.documents["b1992_0"] == citing
        assert "Schneeverwehungen" not in fake_project.documents["b1992_0"]
        assert "EN 1992-1-1" in caplog.text

    def test_the_published_typo_is_left_alone_and_logged(self, fake_project, caplog):
        # B 1993-1-1 really references ÖNORM EN 1933-1-1, a typo for 1993
        # (docs/norm-graph.md). Resolution must never silently rewrite the
        # reference and never silently drop it.
        typo_chunk = (
            "5.2.1 Festlegung zu ÖNORM EN 1933-1-1, Abschnitt 5.2.1\n"
            "Der empfohlene Wert wird übernommen."
        )
        steel_chunk = "5.2.1 Einfluss der Tragwerksverformung\nTheorie II. Ordnung."
        _add(fake_project, "b1993", "ÖNORM B 1993-1-1", [typo_chunk])
        _add(fake_project, "en1993", "ÖNORM EN 1993-1-1", [steel_chunk])

        with caplog.at_level(logging.WARNING):
            assert enrich_project_references("p") == 0

        assert fake_project.documents["b1993_0"] == typo_chunk
        assert "EN 1933-1-1" in caplog.text

    def test_a_self_reference_is_not_enriched_and_not_warned_about(
        self, fake_project, caplog
    ):
        # A norm cites its own clauses constantly; that is neither an
        # enrichment opportunity nor an unresolved reference worth a log
        # line per pass.
        self_citing = "4.2 Für die Betondeckung gilt ÖNORM EN 1992-1-1, Abschnitt 3.1.6."
        _add(fake_project, "en", "ÖNORM EN 1992-1-1", [EN_CHUNK, self_citing])

        with caplog.at_level(logging.WARNING):
            assert enrich_project_references("p") == 0

        assert fake_project.documents["en_1"] == self_citing
        assert "Unresolved" not in caplog.text

    def test_an_empty_project_is_a_no_op(self, fake_project):
        assert enrich_project_references("p") == 0


class TestRetrievalSeesOriginalTextOnly:
    @pytest.fixture()
    def retrieval(self, monkeypatch, fake_project):
        monkeypatch.setattr(llm_module, "get_collection", lambda project_id: fake_project)
        monkeypatch.setattr(llm_module, "get_embeddings", lambda: FakeEmbeddings())
        monkeypatch.setattr(
            llm_module, "bm25_rank_ids", lambda question, ids, docs: list(ids)
        )
        monkeypatch.setattr(
            llm_module,
            "rerank_ids",
            lambda question, ids, docs, top_k: list(ids)[:top_k],
        )
        return fake_project

    def test_chunk_text_is_the_original_not_the_indexed_text(self, retrieval):
        _add(retrieval, "en", "ÖNORM EN 1992-1-1", [EN_CHUNK])
        _add(retrieval, "b", "ÖNORM B 1992-1-1", [B_CHUNK])
        enrich_project_references("p")
        assert retrieval.documents["b_0"] != B_CHUNK

        sources = retrieve_sources("p", "Wie wird die Betondruckfestigkeit bestimmt?")

        by_document = {source.document_id: source for source in sources}
        assert by_document["b"].chunk_text == B_CHUNK

    def test_collections_indexed_before_enrichment_still_answer(self, retrieval):
        # Chunks written before this feature carry no raw_text; their
        # stored text is already the original and must be served as-is.
        _add(retrieval, "en", "ÖNORM EN 1992-1-1", [EN_CHUNK])

        sources = retrieve_sources("p", "Betondruckfestigkeit")

        assert sources[0].chunk_text == EN_CHUNK

    def test_appended_text_cannot_be_selected_as_a_highlight_span(self, retrieval):
        # _ground_excerpt picks the closest real span of chunk_text so the
        # on-page PDF search is guaranteed to find it. Even if the model
        # quotes the appended parent heading, grounding runs against the
        # original text and can never return a span that is not on the
        # cited page.
        _add(retrieval, "en", "ÖNORM EN 1992-1-1", [EN_CHUNK])
        _add(retrieval, "b", "ÖNORM B 1992-1-1", [B_CHUNK])
        enrich_project_references("p")

        sources = retrieve_sources("p", "Betondruckfestigkeit")
        annex = {source.document_id: source for source in sources}["b"]

        assert annex.chunk_text == B_CHUNK
        grounded = _ground_excerpt(EN_HEADING, annex.chunk_text)
        # Every candidate span is built from lines of the original text,
        # so the appended heading can never be what gets highlighted.
        assert grounded is None or EN_HEADING not in grounded


class TestIngestionFlag:
    @pytest.fixture()
    def ingestion(self, monkeypatch, tmp_path, fake_project):
        import services.ingestion as ingestion_module
        from services.chunking import PageText

        monkeypatch.setattr(
            ingestion_module,
            "extract_pages",
            lambda path: [PageText(page_number=1, text=B_CHUNK)],
        )
        monkeypatch.setattr(
            ingestion_module, "get_collection", lambda project_id: fake_project
        )
        monkeypatch.setattr(ingestion_module, "get_embeddings", lambda: FakeEmbeddings())
        monkeypatch.setattr(
            ingestion_module, "get_project_documents_dir", lambda project_id: tmp_path
        )
        calls = []
        monkeypatch.setattr(
            ingestion_module,
            "enrich_project_references",
            lambda project_id: calls.append(project_id),
        )
        return ingestion_module, calls

    def test_the_flag_defaults_to_on(self):
        # Surfacing a European clause with its national modification is the
        # capability the product exists for, and delta admission is inert
        # without the raw_text this pass records.
        from config import Settings

        assert Settings(_env_file=None).reference_enrichment_enabled is True

    def test_no_enrichment_pass_when_the_flag_is_off(
        self, db_session, project, ingestion, monkeypatch
    ):
        # Set explicitly rather than leaning on the default, which is now on.
        ingestion_module, calls = ingestion
        monkeypatch.setattr(
            ingestion_module.settings, "reference_enrichment_enabled", False
        )
        ingestion_module.ingest_document(
            db_session, project.id, "OENORM_B_1992_1_1_2018_01_01.pdf", b"pdfbytes"
        )
        assert calls == []

    def test_enrichment_pass_runs_after_ingestion_when_the_flag_is_on(
        self, db_session, project, ingestion, monkeypatch
    ):
        ingestion_module, calls = ingestion
        monkeypatch.setattr(
            ingestion_module.settings, "reference_enrichment_enabled", True
        )
        document = ingestion_module.ingest_document(
            db_session, project.id, "OENORM_B_1992_1_1_2018_01_01.pdf", b"pdfbytes"
        )
        assert calls == [project.id]
        assert document.chunk_count > 0

    def test_an_enrichment_failure_does_not_fail_the_upload(
        self, db_session, project, ingestion, monkeypatch, caplog
    ):
        ingestion_module, calls = ingestion
        monkeypatch.setattr(
            ingestion_module.settings, "reference_enrichment_enabled", True
        )

        def boom(project_id):
            raise RuntimeError("enrichment exploded")

        monkeypatch.setattr(ingestion_module, "enrich_project_references", boom)
        with caplog.at_level(logging.ERROR):
            document = ingestion_module.ingest_document(
                db_session, project.id, "OENORM_B_1992_1_1_2018_01_01.pdf", b"pdfbytes"
            )
        assert document.id is not None
        assert "Reference enrichment failed" in caplog.text

    def test_enrich_false_defers_the_pass_to_the_caller(
        self, db_session, project, ingestion, monkeypatch
    ):
        # A batch caller ingests every file with enrich=False and runs
        # run_enrichment_pass() itself, once after the last file.
        ingestion_module, calls = ingestion
        monkeypatch.setattr(
            ingestion_module.settings, "reference_enrichment_enabled", True
        )
        for filename in (
            "OENORM_B_1992_1_1_2018_01_01.pdf",
            "OENORM_EN_1992_1_1_2015_02_15.pdf",
        ):
            ingestion_module.ingest_document(
                db_session, project.id, filename, b"pdfbytes", enrich=False
            )
        assert calls == []

        ingestion_module.run_enrichment_pass(project.id)
        assert calls == [project.id]

    def test_run_enrichment_pass_respects_the_flag(self, ingestion, monkeypatch):
        ingestion_module, calls = ingestion
        monkeypatch.setattr(
            ingestion_module.settings, "reference_enrichment_enabled", False
        )
        ingestion_module.run_enrichment_pass("p")
        assert calls == []


class TestBatchUploadEndpoint:
    """One multi-file request pays one enrichment pass, not one per file."""

    @pytest.fixture()
    def ingestion_calls(self, monkeypatch, tmp_path, fake_project):
        import services.ingestion as ingestion_module
        from services.chunking import PageText

        def fake_extract_pages(path):
            if "kaputt" in path:
                raise RuntimeError("PDF nicht lesbar")
            return [PageText(page_number=1, text=B_CHUNK)]

        monkeypatch.setattr(ingestion_module, "extract_pages", fake_extract_pages)
        monkeypatch.setattr(
            ingestion_module, "get_collection", lambda project_id: fake_project
        )
        monkeypatch.setattr(ingestion_module, "get_embeddings", lambda: FakeEmbeddings())
        monkeypatch.setattr(
            ingestion_module, "get_project_documents_dir", lambda project_id: tmp_path
        )
        monkeypatch.setattr(
            ingestion_module.settings, "reference_enrichment_enabled", True
        )
        calls = []
        monkeypatch.setattr(
            ingestion_module,
            "enrich_project_references",
            lambda project_id: calls.append(project_id),
        )
        return calls

    @staticmethod
    def _pdf(name):
        return ("file", (name, b"pdfbytes", "application/pdf"))

    def test_a_multi_file_upload_runs_one_enrichment_pass(
        self, client, project, ingestion_calls
    ):
        response = client.post(
            f"/api/projects/{project.id}/documents",
            files=[
                self._pdf("OENORM_B_1992_1_1_2018_01_01.pdf"),
                self._pdf("OENORM_EN_1992_1_1_2015_02_15.pdf"),
            ],
        )
        assert response.status_code == 201
        assert len(response.json()) == 2
        assert ingestion_calls == [project.id]

    def test_a_single_file_upload_still_enriches_once(
        self, client, project, ingestion_calls
    ):
        response = client.post(
            f"/api/projects/{project.id}/documents",
            files=[self._pdf("OENORM_B_1992_1_1_2018_01_01.pdf")],
        )
        assert response.status_code == 201
        assert len(response.json()) == 1
        assert ingestion_calls == [project.id]

    def test_files_ingested_before_a_failure_are_still_enriched(
        self, client, project, ingestion_calls
    ):
        response = client.post(
            f"/api/projects/{project.id}/documents",
            files=[self._pdf("gut.pdf"), self._pdf("kaputt.pdf")],
        )
        assert response.status_code == 500
        assert ingestion_calls == [project.id]

    def test_a_non_pdf_rejects_the_batch_before_ingesting_anything(
        self, client, project, ingestion_calls
    ):
        response = client.post(
            f"/api/projects/{project.id}/documents",
            files=[self._pdf("gut.pdf"), ("file", ("notizen.txt", b"x", "text/plain"))],
        )
        assert response.status_code == 400
        assert ingestion_calls == []


class TestGermanNationalAnnexReferences:
    """DIN national annexes never name the norm they modify.

    They write "NDP zu 6.2.3(2)" — nationally determined parameter — or
    "NCI zu 6.2.3" for complementary information. Measured on the DIN corpus:
    1,487 occurrences across 51 documents, of which exactly one also names
    the norm. Enrichment consequently resolved 4 chunks out of 21,909 German
    ones, against 565 out of 10,511 Austrian.
    """

    NDP = "NDP zu 6.2.3(2)\nEs gilt der empfohlene Wert."
    NCI = "NCI zu 9.2.2\nErgänzende Regelungen zur Querkraftbewehrung."

    def test_ndp_resolves_against_the_annex_parent(self):
        (ref,) = extract_clause_references(self.NDP, "DIN EN 1992-1-1/NA")
        assert (ref.designation, ref.clause) == ("EN 1992-1-1", "6.2.3")

    def test_nci_is_recognised_too(self):
        (ref,) = extract_clause_references(self.NCI, "DIN EN 1992-1-1/NA")
        assert (ref.designation, ref.clause) == ("EN 1992-1-1", "9.2.2")

    def test_an_amended_annex_still_resolves_to_the_base_norm(self):
        (ref,) = extract_clause_references(self.NDP, "DIN EN 1990/NA/A1")
        assert ref.designation == "EN 1990"

    def test_a_bare_reference_outside_an_annex_is_not_resolved(self):
        # The rule the exception is carved out of: several documents in a
        # project share clause numbers, so "NDP zu 6.2.3" in an ordinary
        # document cannot be attributed to any one of them.
        assert extract_clause_references(self.NDP, "DIN EN 1992-1-1") == []
        assert extract_clause_references(self.NDP) == []

    def test_the_austrian_form_is_unaffected(self):
        text = (
            "6.1.4 Festlegung zu ÖNORM EN 1992-1-1:2015, Abschnitt 3.1.6(1)P\n"
            "Der empfohlene Wert wird übernommen."
        )
        (ref,) = extract_clause_references(text, "ÖNORM B 1992-1-1")
        assert (ref.designation, ref.clause) == ("EN 1992-1-1", "3.1.6")

    def test_annex_letter_clauses_are_left_alone(self):
        # "NDP zu A2.3.1" — 57 of the 1,487. Chunk headings are digits-only,
        # so such a clause has nothing to resolve against and matching it
        # would only produce unresolved-reference log noise.
        assert extract_clause_references("NDP zu A2.3.1 (5)", "DIN EN 1990/NA") == []

    def test_a_top_level_reference_is_not_a_clause(self):
        # Mirrors the existing rule: only sub-level numbers become headings.
        assert extract_clause_references("NDP zu 6 Anmerkung", "DIN EN 1990/NA") == []
