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


def test_replaces_parenthesised_prose_label():
    # Produced by an actual eval run and shipped to the user untouched:
    # the old pattern only matched the bracketed form.
    sources = [_source("en.pdf", norm_reference="ÖNORM EN 1995-1-2"),
               _source("b.pdf", norm_reference="ÖNORM B 1995-1-2")]
    answer = "Diese Norm ist anzuwenden (siehe Quelle 1 und 2)."

    result = _replace_citation_labels(answer, sources)

    assert result == "Diese Norm ist anzuwenden (siehe ÖNORM EN 1995-1-2 und ÖNORM B 1995-1-2)."


def test_replaces_bare_label_without_brackets():
    sources = [_source("din_4102.pdf", norm_reference="DIN 4102-2")]

    assert _replace_citation_labels("Nach Quelle 1 gilt.", sources) == "Nach DIN 4102-2 gilt."


def test_preserves_the_separator_style_the_model_used():
    sources = [_source("a.pdf", norm_reference="A"), _source("b.pdf", norm_reference="B"),
               _source("c.pdf", norm_reference="C")]

    assert _replace_citation_labels("(Quellen 1, 2 und 3)", sources) == "(A, B und C)"


def test_leaves_out_of_range_prose_label_untouched():
    sources = [_source("din_4102.pdf", norm_reference="DIN 4102-2")]

    assert _replace_citation_labels("(siehe Quelle 7)", sources) == "(siehe Quelle 7)"
