from pathlib import Path

from scripts.ingest_corpus import batched, discover_pdfs, pending


def test_discover_pdfs_skips_appledouble_sidecars(tmp_path: Path):
    """macOS writes `._Foo.pdf` beside every file on the exFAT corpus volume.

    They match *.pdf and are not PDFs, so including them would double the
    upload and create documents that parse to nothing.
    """
    (tmp_path / "EN 1992").mkdir()
    (tmp_path / "EN 1992" / "DIN EN 1992-1-1.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "EN 1992" / "._DIN EN 1992-1-1.pdf").write_bytes(b"\x00\x05\x16\x07")
    (tmp_path / ".DS_Store").write_bytes(b"junk")
    (tmp_path / "notes.txt").write_text("not a pdf")

    found = discover_pdfs(tmp_path)

    assert [path.name for path in found] == ["DIN EN 1992-1-1.pdf"]


def test_discover_pdfs_recurses_and_sorts(tmp_path: Path):
    for subdir, name in (("9", "b.pdf"), ("0", "a.pdf")):
        (tmp_path / subdir).mkdir()
        (tmp_path / subdir / name).write_bytes(b"%PDF-1.4")

    found = discover_pdfs(tmp_path)

    assert [path.name for path in found] == ["a.pdf", "b.pdf"]


def test_pending_skips_filenames_the_project_already_holds(tmp_path: Path):
    """A resumed run must not re-upload: the server renames duplicates
    (`foo.pdf` -> `foo_1.pdf`) rather than rejecting them, which would
    silently double the corpus."""
    paths = [tmp_path / "a.pdf", tmp_path / "b.pdf", tmp_path / "c.pdf"]

    assert [path.name for path in pending(paths, {"a.pdf", "c.pdf"})] == ["b.pdf"]


def test_pending_returns_everything_for_an_empty_project(tmp_path: Path):
    paths = [tmp_path / "a.pdf", tmp_path / "b.pdf"]

    assert pending(paths, set()) == paths


def test_batched_covers_every_item_including_a_short_final_batch(tmp_path: Path):
    paths = [tmp_path / f"{index}.pdf" for index in range(7)]

    batches = list(batched(paths, 3))

    assert [len(batch) for batch in batches] == [3, 3, 1]
    assert [path for batch in batches for path in batch] == paths


def test_resolve_credentials_prefers_explicit_environment(monkeypatch):
    from scripts.ingest_corpus import resolve_credentials

    environ = {"NORMCHAT_USERNAME": "ops", "NORMCHAT_PASSWORD": "secret"}

    assert resolve_credentials(environ) == ("ops", "secret")


def test_resolve_credentials_falls_back_to_settings(monkeypatch):
    """The common case: reuse what `Settings` read from backend/.env, so a
    routine ingest needs no password typed on a command line."""
    from config import settings
    from scripts.ingest_corpus import resolve_credentials

    monkeypatch.setattr(settings, "auth_username", "from-env-file")
    monkeypatch.setattr(settings, "auth_password", "also-from-env-file")

    assert resolve_credentials({}) == ("from-env-file", "also-from-env-file")


def test_resolve_credentials_ignores_a_half_configured_environment(monkeypatch):
    """A username with no password must not shadow the .env pair, or the run
    would authenticate as nobody and fail late."""
    from config import settings
    from scripts.ingest_corpus import resolve_credentials

    monkeypatch.setattr(settings, "auth_username", "from-env-file")
    monkeypatch.setattr(settings, "auth_password", "also-from-env-file")

    assert resolve_credentials({"NORMCHAT_USERNAME": "ops"}) == (
        "from-env-file",
        "also-from-env-file",
    )


def test_pending_matches_across_unicode_normalisation_forms(tmp_path):
    """macOS hands back decomposed filenames; a name that reached the server
    as a composed literal comes back composed. Comparing raw strings re-uploads
    a file that is already there, and the server renames rather than rejects
    it, so the corpus silently grows a duplicate."""
    import unicodedata

    name = "DIN EN 1999-1-4 Kaltgeformte Profiltafeln für den Hochbau.pdf"
    decomposed = unicodedata.normalize("NFD", name)
    composed = unicodedata.normalize("NFC", name)
    assert decomposed != composed

    assert pending([tmp_path / decomposed], {composed}) == []
    assert pending([tmp_path / composed], {decomposed}) == []
