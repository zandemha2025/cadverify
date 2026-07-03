"""Parse the analyzers' free-text ``cite=`` strings into structured Citations.

Historically each DFM check baked a citation string straight into
``Issue.fix_suggestion`` (e.g. ``"Increase wall thickness … NADCA §3: 1° min
external."``). That text is unstructured — a UI or audit report cannot pull the
standard out of it reliably. ``parse_citation`` promotes those strings into a
:class:`~src.analysis.models.Citation` ``{standard?, clause?, text?}`` object.

Parsing is deliberately conservative and best-effort: it never fabricates a
``rule_id`` and — critically — never invents a ``standard`` out of a descriptive
sentence. The rules, in order:

1. Pull a section marker (``§3``, ``§3.1``, ``§ 4.2``) out as ``clause``.
2. If a colon *followed by whitespace* delimits the string (``STANDARD: detail``),
   split there — but ``standard`` = left ONLY when the left side actually reads
   as a citation source (a standards body / spec / vendor guide). When the left
   side is a generic process/material/geometry descriptor (``"3-axis: …"``,
   ``"Forging: …"``, ``"Metal powder: …"``) the colon merely introduces an
   explanatory clause, so the WHOLE string becomes ``text`` with no fabricated
   ``standard``. (A colon *inside* a token such as ``ISO/ASTM 52910:2018`` is NOT
   a delimiter and is left intact.)
3. Otherwise the string is either a bare source identifier (``"Sodick ALC600G."``)
   or an advisory sentence (``"Wire EDM cuts a 2D profile extruded in Z."``). A
   sentence — anything containing a common lowercase word or sentence
   punctuation (``;`` ``—`` ``→``) — becomes ``text`` with no ``standard``; only a
   clean identifier is promoted to ``standard``. When unsure we prefer ``text``:
   a citation with the wrong ``standard`` is worse than one carrying only text.

Examples:
    * ``"NADCA §3: 1° min external, 2° internal."``
        -> standard="NADCA", clause="§3", text="1° min external, 2° internal."
    * ``"ISO/ASTM 52910:2018 §5.3."``
        -> standard="ISO/ASTM 52910:2018", clause="§5.3", text=None
    * ``"Sodick ALC600G."``
        -> standard="Sodick ALC600G.", text=None
    * ``"Wire EDM cuts a 2D profile extruded in Z."``
        -> standard=None, text="Wire EDM cuts a 2D profile extruded in Z."
    * ``"3-axis: tool access from +Z only."``
        -> standard=None, text="3-axis: tool access from +Z only." (descriptor,
        not a source — no fabricated standard)
"""

from __future__ import annotations

import re
from typing import Optional

from src.analysis.models import Citation

# A section/clause marker like "§3", "§3.1", "§ 4.2". Captured out of the string
# so the source name / detail text stay clean.
_CLAUSE_RE = re.compile(r"§\s*[0-9]+(?:\.[0-9]+)*[A-Za-z]?")

# A colon that delimits "STANDARD: detail" — i.e. followed by whitespace or end
# of string. This deliberately does NOT match a colon inside a token such as the
# version in "ISO/ASTM 52910:2018".
_DELIM_RE = re.compile(r":(?:\s|$)")

# Sentence punctuation that reliably marks advisory prose rather than a source
# identifier in the current cite corpus.
_SENTENCE_PUNCT = (";", "—", "→")

# Generic manufacturing descriptors — process names, material states, and
# geometry/axis terms. These are NOT citation sources: a cite like
# ``"3-axis: tool access from +Z only."`` or ``"Forging: no undercuts …"`` uses
# the colon to introduce an explanatory clause, not to name a standard, so the
# left side must NOT be promoted to ``standard``. Curated because surface form
# alone cannot tell the process word "Forging" from a vendor name like "Sandvik";
# every entry is verified absent from the genuine sources in the real cite=
# corpus (e.g. "metal" is deliberately excluded — it appears in the vendor
# "Desktop Metal"). Matched case-insensitively, per hyphen/space/slash token.
_DESCRIPTOR_WORDS = frozenset({
    "axis", "forging", "casting", "molding", "moulding", "machining",
    "milling", "turning", "welding", "sintering", "extrusion",
    "powder", "resin", "filament", "green", "part",
    "undercut", "undercuts", "overhang", "overhangs",
})


def _looks_like_source_left(left: str) -> bool:
    """True when the left of a ``STANDARD: detail`` split is a real citation source.

    A real source is a standards body / spec / vendor guide (``AFS``, ``DIN 6935``,
    ``EOS M 400-4``, ``Sandvik``). It is NOT a generic manufacturing descriptor
    (``3-axis``, ``Forging``, ``Metal powder``, ``Multi-axis DED``): those use the
    colon to introduce an explanatory clause, so the whole cite must stay free
    text with a null ``standard``.

    Unlike the colon-less prose guard, this does NOT reject on lowercase words —
    genuine vendor sources legitimately contain them ("EOS DMLS best practice",
    "EOS Ti/Inconel data sheets"). It rejects only when a known
    process/material/geometry descriptor token is present (hyphens split too, so
    "3-axis" and "Multi-axis" expose the "axis" descriptor), plus advisory
    sentence punctuation, which a source name never carries.
    """
    if any(p in left for p in _SENTENCE_PUNCT):
        return False
    for tok in re.split(r"[\s/\-]+", left):
        if tok.strip(".,()[]").lower() in _DESCRIPTOR_WORDS:
            return False
    return True


def _looks_like_source(text: str) -> bool:
    """True when a colon-less string reads as a source identifier, not prose.

    Heuristic: a source identifier (a spec code or a vendor/machine name) has no
    common lowercase word and no sentence punctuation. A descriptive sentence
    ("cuts a 2D profile", "walls vibrate") always trips a lowercase word. This
    errs toward prose — an identifier that slips through simply lands in ``text``
    (honest) rather than being asserted as a wrong ``standard``.
    """
    if any(p in text for p in _SENTENCE_PUNCT):
        return False
    for tok in re.split(r"[\s/]+", text):
        word = tok.strip(".,()[]")
        if len(word) >= 3 and word.isalpha() and word.islower():
            return False
    return True


def parse_citation(cite: Optional[str]) -> Optional[Citation]:
    """Parse a free-text cite string into a structured Citation, or None.

    Returns ``None`` for empty/blank input so issues without a citation stay
    genuinely uncited (no empty object masquerading as a real reference).
    """
    if not cite:
        return None
    raw = cite.strip()
    if not raw:
        return None

    # 1. Clause marker (searched across the whole string, then stripped out).
    clause: Optional[str] = None
    m = _CLAUSE_RE.search(raw)
    working = raw
    if m:
        clause = m.group(0).replace(" ", "")
        working = _CLAUSE_RE.sub("", raw)
    working = re.sub(r"\s{2,}", " ", working).strip()
    # Tidy the dangling " ." a clause removal can leave ("… DFM §3." -> "… DFM .").
    working = re.sub(r"\s+\.", ".", working).strip()

    # 2. "STANDARD: detail" delimiter (colon followed by whitespace/end).
    dm = _DELIM_RE.search(working)
    if dm:
        left = working[: dm.start()].strip(" .")
        right = working[dm.end():].strip() or None
        # Promote the left side to ``standard`` ONLY when it actually reads as a
        # citation source. A generic process/material/geometry descriptor
        # ("3-axis", "Forging", "Metal powder") names a process, not a reference:
        # asserting standard="3-axis" would fabricate a standard. In that case
        # keep the WHOLE cite as honest free text with no fabricated standard.
        if left and _looks_like_source_left(left):
            return Citation(standard=left or None, text=right, clause=clause)
        whole = working.strip(" .") or None
        return Citation(standard=None, text=whole, clause=clause)

    # 3. No delimiter: bare identifier vs advisory sentence.
    if not working:
        return Citation(standard=None, text=None, clause=clause)
    if _looks_like_source(working):
        return Citation(standard=working.strip(" .") or None, text=None, clause=clause)
    return Citation(standard=None, text=working, clause=clause)
