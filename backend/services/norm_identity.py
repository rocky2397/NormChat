"""Structured identity for an uploaded norm document.

A norm is identified by more than a name: `DIN EN 1990`, `DIN EN 1990/NA` and
`DIN EN 1990/NA/A1` are three different documents, and an engineer citing one
has not cited the others. The first is the adopted European norm, the second
is the German National Annex that sets the nationally determined parameters,
and only both together state what actually applies in Germany. Treating
identity as one opaque string loses that distinction — the earlier
filename/first-page regex resolved all three to `DIN EN 1990`.

Identity is read from the cover page, because that is the document's own
statement of what it is; the filename is only a hint and may be anything the
user's filesystem happens to hold.
"""

import re
from dataclasses import dataclass
from typing import Callable

_NON_BREAKING_SPACE = " "
_NON_BREAKING_HYPHEN = "‑"

_GERMAN_MONTHS = {
    "januar": "01", "februar": "02", "märz": "03", "april": "04",
    "mai": "05", "juni": "06", "juli": "07", "august": "08",
    "september": "09", "oktober": "10", "november": "11", "dezember": "12",
}


def normalize_reference_text(text: str) -> str:
    """Flattens a norm reference to a single canonical line.

    Typeset references carry non-breaking spaces and hyphens, and wrap across
    lines mid-reference (`"ÖNORM \\nEN 1992-1-1"`), so the same norm appears
    in several byte sequences that must compare equal.
    """
    text = text.replace(_NON_BREAKING_SPACE, " ").replace(_NON_BREAKING_HYPHEN, "-")
    return " ".join(text.split())


@dataclass(frozen=True)
class NormIdentity:
    publisher: str
    designation: str
    number: str
    national_annex: bool
    amendment: str | None
    edition: str | None
    jurisdiction: str

    @property
    def reference(self) -> str:
        """Display form, e.g. `DIN EN 1990/NA` — what a citation shows.

        Built from the designation exactly as the document prints it, rather
        than re-rendered from the parts, so each publisher's own convention
        survives without this module encoding formatting rules per country.
        """
        return f"{self.publisher} {self.designation}"

    @property
    def key(self) -> str:
        """Edition-independent match key: the same norm across its editions."""
        return f"{self.jurisdiction}:{self.publisher}:{self.designation}"

    @property
    def versioned_key(self) -> str:
        return f"{self.key}:{self.edition}" if self.edition else self.key


@dataclass(frozen=True)
class NormProfile:
    """How one issuing body states a document's identity on its cover.

    Adding a country means adding a profile, not changing the parser. Each
    carries its own parse step because the publishers differ in more than
    wording: ÖNORM prints the edition immediately after the designation,
    which is what separates it from the superseded edition named a few lines
    above, while DIN prints a German month and year at the head of the page.

    Anything no profile recognises falls back to the older reference regexes
    in services/storage.py and keeps working as before.
    """

    name: str
    jurisdiction: str
    publisher: str
    from_cover: Callable[[str], "NormIdentity | None"]
    from_filename: Callable[[str], "NormIdentity | None"]


# --- Austria (ÖNORM, Austrian Standards) ------------------------------------
#
# Cover reads `ÖNORM` / designation / `Ausgabe: <iso date>`. Requiring the
# edition line to follow the designation is what separates the document's own
# identity from the other references printed on the same cover — notably
# `Ersatz für ÖNORM B 1992-1-1:2011-12`, which names a different edition of
# this very norm.
_AT_COVER = re.compile(
    r"ÖNORM\s+(?P<series>EN|B)\s+(?P<number>\d+(?:-\d+)*)"
    r"\s*(?:/\s*(?P<amendment>A\d+))?"
    r"\s+Ausgabe:\s*(?P<edition>\d{4}-\d{2}-\d{2})"
)
_AT_FILENAME = re.compile(
    r"OENORM_(?P<series>EN|B)_(?P<number>\d+(?:-\d+)*)"
    r"(?:_(?P<amendment>A\d+))?"
    r"_(?P<y>\d{4})_(?P<m>\d{2})_(?P<d>\d{2})",
    re.IGNORECASE,
)


def _austria_identity(series: str, number: str, amendment: str | None, edition: str | None):
    designation = f"{series} {number}"
    if amendment:
        designation = f"{designation}/{amendment}"
    return NormIdentity(
        publisher="ÖNORM",
        designation=designation,
        number=number,
        # Austria publishes its national annex as a separate B series.
        national_annex=series.upper() == "B",
        amendment=amendment,
        edition=edition,
        jurisdiction="AT",
    )


def _austria_from_cover(text: str) -> NormIdentity | None:
    # Flattened: the ÖNORM cover splits its designation across lines
    # ("ÖNORM" / "EN 1992-1-1" / "Ausgabe: …"), so the adjacency this pattern
    # relies on only exists once the line breaks are collapsed.
    match = _AT_COVER.search(normalize_reference_text(text))
    if not match:
        return None
    return _austria_identity(
        match.group("series"), match.group("number"),
        match.group("amendment"), match.group("edition"),
    )


def _austria_from_filename(filename: str) -> NormIdentity | None:
    match = _AT_FILENAME.search(filename)
    if not match:
        return None
    amendment = match.group("amendment")
    return _austria_identity(
        match.group("series").upper(), match.group("number"),
        amendment.upper() if amendment else None,
        f"{match.group('y')}-{match.group('m')}-{match.group('d')}",
    )


# --- Germany (DIN, Deutsches Institut für Normung) ---------------------------
#
# Cover reads `DIN EN <number>`, with `/NA` for the National Annex, a
# trailing `/A<n>` for an amendment (`DIN EN 1990/NA/A1`), and
# `Berichtigung <n>` for a corrigendum.
#
# Matched against a cover line in full, not searched for anywhere on the
# page: the document's own designation stands alone on its own line, whereas
# every reference to a *different* document sits inside prose ("Berichtigung
# zu DIN EN 1991-3:2010-12"). Searching the flattened page instead makes an
# EN norm that merely mentions its National Annex resolve to the annex —
# collapsing exactly the distinction this module exists to draw.
_DE_COVER_LINE = re.compile(
    r"^DIN\s+EN\s+(?P<number>\d{4}(?:-\d{1,2})*)"
    r"(?P<na>/NA)?"
    r"(?:/(?P<amendment>A\d+))?"
    r"(?:\s+Berichtigung\s+(?P<corrigendum>\d+))?$"
)
_DE_EDITION = re.compile(
    r"\b(?P<month>" + "|".join(_GERMAN_MONTHS) + r")\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
# A four-digit Eurocode number followed by one- or two-digit parts; without
# that bound the number swallows a trailing edition date (`1991-1-2-2010-12`).
_DE_FILENAME = re.compile(
    r"DIN\s+EN\s+(?P<number>\d{4}(?:-\d{1,2}(?!\d))*)"
    r"(?P<na>-NA)?"
    r"(?:-(?P<amendment>A\d+))?",
    re.IGNORECASE,
)


def _germany_identity(
    number: str,
    na: bool,
    amendment: str | None,
    corrigendum: str | None,
    edition: str | None,
):
    designation = f"EN {number}"
    if na:
        designation += "/NA"
    if amendment:
        designation += f"/{amendment}"
    if corrigendum:
        designation += f" Berichtigung {corrigendum}"
    return NormIdentity(
        publisher="DIN",
        designation=designation,
        number=number,
        national_annex=na,
        amendment=amendment,
        edition=edition,
        jurisdiction="DE",
    )


def _germany_edition(text: str) -> str | None:
    match = _DE_EDITION.search(text)
    if not match:
        return None
    return f"{match.group('year')}-{_GERMAN_MONTHS[match.group('month').lower()]}"


def _germany_from_cover(text: str) -> NormIdentity | None:
    for line in text.split("\n"):
        match = _DE_COVER_LINE.match(normalize_reference_text(line))
        if match:
            return _germany_identity(
                match.group("number"), bool(match.group("na")),
                match.group("amendment"), match.group("corrigendum"),
                _germany_edition(normalize_reference_text(text)),
            )
    return None


def _germany_from_filename(filename: str) -> NormIdentity | None:
    match = _DE_FILENAME.search(filename)
    if not match:
        return None
    amendment = match.group("amendment")
    return _germany_identity(
        match.group("number"), bool(match.group("na")),
        amendment.upper() if amendment else None, None, None,
    )


AUSTRIA = NormProfile(
    name="ÖNORM (Austrian Standards)",
    jurisdiction="AT",
    publisher="ÖNORM",
    from_cover=_austria_from_cover,
    from_filename=_austria_from_filename,
)

GERMANY = NormProfile(
    name="DIN (Deutsches Institut für Normung)",
    jurisdiction="DE",
    publisher="DIN",
    from_cover=_germany_from_cover,
    from_filename=_germany_from_filename,
)

PROFILES: tuple[NormProfile, ...] = (AUSTRIA, GERMANY)


def parse_identity(filename: str, first_page_text: str = "") -> NormIdentity | None:
    """Identity from the cover page, falling back to the filename.

    The cover wins because it is the document's own declaration; the filename
    only carries weight when the first page yields nothing useful, as with a
    scan whose cover did not extract.
    """
    # Passed raw: profiles differ in whether line structure matters. DIN needs
    # it (the designation is a standalone line); ÖNORM needs it collapsed.
    for profile in PROFILES:
        identity = profile.from_cover(first_page_text)
        if identity:
            return identity
    for profile in PROFILES:
        identity = profile.from_filename(filename)
        if identity:
            return identity
    return None
