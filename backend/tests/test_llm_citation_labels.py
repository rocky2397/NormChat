from models.chat import SourceChunk
from services.llm import _replace_citation_labels


def _source(filename, norm_reference=None):
    return SourceChunk(
        document_id="doc-1",
        filename=filename,
        page_number=1,
        chunk_text="...",
        norm_reference=norm_reference,
    )


def test_replaces_citation_label_with_norm_reference():
    sources = [_source("din_4102.pdf", norm_reference="DIN 4102-2")]
    answer = "Gemäß [Quelle 1] müssen Brandwände feuerbeständig sein."

    result = _replace_citation_labels(answer, sources)

    assert result == "Gemäß DIN 4102-2 müssen Brandwände feuerbeständig sein."


def test_falls_back_to_filename_without_norm_reference():
    sources = [_source("anhang.pdf")]
    answer = "Siehe [Quelle 1] für Details."

    result = _replace_citation_labels(answer, sources)

    assert result == "Siehe anhang.pdf für Details."


def test_leaves_out_of_range_label_untouched():
    sources = [_source("din_4102.pdf", norm_reference="DIN 4102-2")]
    answer = "Wie in [Quelle 3] beschrieben."

    result = _replace_citation_labels(answer, sources)

    assert result == "Wie in [Quelle 3] beschrieben."
