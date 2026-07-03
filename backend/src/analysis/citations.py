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
   split there — ``standard`` = left, ``text`` = right. (A colon *inside* a token
   such as ``ISO/ASTM 52910:2018`` is NOT a delimiter and is left intact.)
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
        standard = working[: dm.start()].strip(" .") or None
        text = working[dm.end():].strip() or None
        return Citation(standard=standard, text=text, clause=clause)

    # 3. No delimiter: bare identifier vs advisory sentence.
    if not working:
        return Citation(standard=None, text=None, clause=clause)
    if _looks_like_source(working):
        return Citation(standard=working.strip(" .") or None, text=None, clause=clause)
    return Citation(standard=None, text=working, clause=clause)
