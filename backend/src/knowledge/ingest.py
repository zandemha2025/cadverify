"""The ingestion pipeline — read a source, keep the knowledge, discard the text.

The design constraint, stated once:

    **Ingest, do not retain.** A source document is held in memory only for as
    long as it takes to extract structured claims from it. The claims are kept.
    The text is not. What persists is a *receipt* — the source identity, a
    content hash, and a locator — which proves what was read without storing it.

That is enforced here rather than promised, by three mechanisms:

1. :class:`IngestionSession` holds source text on a context manager that clears
   it on exit, and refuses to hand it back after close.
2. :func:`longest_shared_ngram` measures verbatim overlap between a source and
   an emitted claim. For a ``facts_only`` source, overlap above the threshold
   raises — you may state what a source establishes, never reproduce how it
   said it.
3. Every emitted claim carries a :class:`SourceReceipt`, so a claim whose
   origin cannot be named cannot be committed.

None of this is legal advice, and none of it substitutes for lawful acquisition
of the source in the first place. See ``INGESTION.md``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterator, Optional, Sequence

from src.knowledge.models import IngestionPolicy, Source

# Overlap at or above this many consecutive words is treated as reproduction
# rather than restatement. Eight is deliberately conservative: ordinary
# engineering phrasing ("minimum wall thickness of the finished part") reaches
# five or six words innocently, and technical terms of art must stay usable.
DEFAULT_NGRAM_THRESHOLD = 8

_WORD_RE = re.compile(r"[a-z0-9]+")


class IngestionError(RuntimeError):
    """The pipeline was asked to do something its policy forbids."""


class VerbatimOverlapError(IngestionError):
    """An extracted claim reproduces the source instead of restating it."""

    def __init__(self, overlap: str, source_id: str, threshold: int) -> None:
        self.overlap = overlap
        self.source_id = source_id
        super().__init__(
            f"claim shares {len(overlap.split())} consecutive words with "
            f"{source_id!r} (threshold {threshold}): {overlap!r}. "
            f"State what the source establishes in your own words, or cite it "
            f"as a quotation if its licence permits."
        )


def _words(text: str) -> list[str]:
    """Normalise to a comparable word sequence.

    Case, punctuation and whitespace are stripped so that overlap detection
    measures substance rather than formatting — reproducing a sentence with the
    commas moved is still reproducing it.
    """
    return _WORD_RE.findall(text.casefold())


def longest_shared_ngram(source_text: str, claim_text: str) -> str:
    """Return the longest run of consecutive words common to both.

    Used to distinguish restatement from reproduction. Returns an empty string
    when nothing is shared.
    """
    source_words = _words(source_text)
    claim_words = _words(claim_text)
    if not source_words or not claim_words:
        return ""

    # Index the source once by n-gram start word, then walk the claim extending
    # matches. O(n*m) worst case but linear in practice on real text.
    best: list[str] = []
    positions: dict[str, list[int]] = {}
    for index, word in enumerate(source_words):
        positions.setdefault(word, []).append(index)

    for claim_index, word in enumerate(claim_words):
        for source_index in positions.get(word, ()):
            length = 0
            while (
                source_index + length < len(source_words)
                and claim_index + length < len(claim_words)
                and source_words[source_index + length]
                == claim_words[claim_index + length]
            ):
                length += 1
            if length > len(best):
                best = claim_words[claim_index : claim_index + length]

    return " ".join(best)


@dataclass(frozen=True)
class SourceReceipt:
    """Proof of what was read, retained in place of the text itself.

    The hash lets you demonstrate later *which* document a claim came from —
    to an auditor, to a publisher, or to yourself — without keeping a copy of
    it. If the same document is ingested again, the hash matches; if the
    publisher issues a new edition, it does not.
    """

    source_id: str
    sha256: str
    locator: str
    byte_length: int
    word_count: int

    @classmethod
    def of(cls, source_id: str, text: str, locator: str) -> "SourceReceipt":
        encoded = text.encode("utf-8")
        return cls(
            source_id=source_id,
            sha256=hashlib.sha256(encoded).hexdigest(),
            locator=locator,
            byte_length=len(encoded),
            word_count=len(_words(text)),
        )


@dataclass(frozen=True)
class ExtractedClaim:
    """One structured claim, ready to become a corpus record.

    Deliberately mirrors the shape of a ``DesignRule``: a claim that cannot say
    what it asserts, why it is true, and where it came from is not admissible.
    """

    statement: str
    why: str
    receipt: SourceReceipt
    kind: str = "design_rule"
    metric: Optional[str] = None
    value_min: Optional[float] = None
    value_typical: Optional[float] = None
    value_max: Optional[float] = None
    units: Optional[str] = None
    processes: tuple[str, ...] = ()
    detects: tuple[str, ...] = ()
    verbatim_quote: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise IngestionError("an extracted claim has no statement")
        if not self.why.strip():
            raise IngestionError(
                f"claim {self.statement[:60]!r} has no `why`; a claim that "
                f"cannot be explained cannot be defended to an auditor"
            )
        has_value = any(
            v is not None for v in (self.value_min, self.value_typical, self.value_max)
        )
        if has_value and not (self.units and self.metric):
            raise IngestionError(
                f"claim {self.statement[:60]!r} carries a value without a "
                f"metric and units"
            )


@dataclass
class IngestionSession:
    """Holds a source document transiently while claims are extracted from it.

    Use as a context manager. On exit the text is dropped and any further
    access raises — so "we do not retain the source" is a property of the type
    rather than a discipline someone has to remember.

        >>> with IngestionSession(source, text, locator="p. 214") as session:
        ...     session.claim(statement="...", why="...")
        >>> session.text  # raises IngestionError
    """

    source: Source
    _text: Optional[str]
    locator: str = "unspecified"
    ngram_threshold: int = DEFAULT_NGRAM_THRESHOLD
    _claims: list[ExtractedClaim] = field(default_factory=list, init=False)
    _receipt: Optional[SourceReceipt] = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

    def __init__(
        self,
        source: Source,
        text: str,
        *,
        locator: str = "unspecified",
        ngram_threshold: int = DEFAULT_NGRAM_THRESHOLD,
    ) -> None:
        if source.ingestion is IngestionPolicy.REFERENCE_ONLY:
            raise IngestionError(
                f"source {source.source_id!r} is reference_only: its existence "
                f"and requirements may be cited, but its content may not be "
                f"processed. Obtain it lawfully and re-classify first."
            )
        if not text.strip():
            raise IngestionError(f"source {source.source_id!r} supplied no text")

        self.source = source
        self.locator = locator
        self.ngram_threshold = ngram_threshold
        self._text = text
        self._claims = []
        self._receipt = SourceReceipt.of(source.source_id, text, locator)
        self._closed = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def __enter__(self) -> "IngestionSession":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Drop the source text. Idempotent."""
        self._text = None
        self._closed = True

    @property
    def text(self) -> str:
        """The source text, while the session is open."""
        if self._closed or self._text is None:
            raise IngestionError(
                "source text was discarded when the session closed — that is "
                "the point. Work from the extracted claims and the receipt."
            )
        return self._text

    @property
    def receipt(self) -> SourceReceipt:
        """Survives the session; this is what gets kept."""
        assert self._receipt is not None
        return self._receipt

    @property
    def claims(self) -> tuple[ExtractedClaim, ...]:
        return tuple(self._claims)

    # ── extraction ───────────────────────────────────────────────────────

    def check_restatement(self, candidate: str) -> None:
        """Raise if ``candidate`` reproduces the source rather than restating it.

        Skipped for sources whose licence permits full ingestion — there,
        quoting is legitimate and the quote belongs in ``verbatim_quote`` with
        its locator.
        """
        if self.source.ingestion is IngestionPolicy.FULL:
            return
        overlap = longest_shared_ngram(self.text, candidate)
        if len(overlap.split()) >= self.ngram_threshold:
            raise VerbatimOverlapError(
                overlap, self.source.source_id, self.ngram_threshold
            )

    def claim(self, *, statement: str, why: str, **kwargs: object) -> ExtractedClaim:
        """Extract one claim, checked against the source it came from.

        Both ``statement`` and ``why`` are checked: a paraphrased headline with
        the source's own explanation pasted underneath is still reproduction.
        """
        self.check_restatement(statement)
        self.check_restatement(why)

        quote = kwargs.get("verbatim_quote")
        if quote is not None and self.source.ingestion is not IngestionPolicy.FULL:
            raise IngestionError(
                f"source {self.source.source_id!r} is {self.source.ingestion.value}; "
                f"a verbatim quote may not be retained from it. Its licence is "
                f"{self.source.licence.value!r}."
            )

        extracted = ExtractedClaim(
            statement=statement,
            why=why,
            receipt=self.receipt,
            **kwargs,  # type: ignore[arg-type]
        )
        self._claims.append(extracted)
        return extracted


def to_design_rule_yaml(
    claim: ExtractedClaim, *, rule_id: str, tier: str, category: str, title: str
) -> dict[str, object]:
    """Render an extracted claim as a ``design_rules.yaml`` entry.

    The last step of the pipeline: structured knowledge out, source text
    nowhere. The result still has to pass the corpus loader's own validation,
    which is deliberate — ingestion is not a side door around the contract.
    """
    entry: dict[str, object] = {
        "rule_id": rule_id,
        "processes": list(claim.processes) or ["all"],
        "category": category,
        "title": title,
        "statement": claim.statement,
        "why": claim.why,
        "relation": "advisory",
        "source_id": claim.receipt.source_id,
        "tier": tier,
    }
    if claim.metric:
        entry["metric"] = claim.metric
    for key in ("value_min", "value_typical", "value_max", "units"):
        value = getattr(claim, key)
        if value is not None:
            entry[key] = value
    if claim.value_min is not None and claim.value_max is not None:
        entry["relation"] = "band"
    elif claim.value_min is not None:
        entry["relation"] = "min"
    elif claim.value_max is not None:
        entry["relation"] = "max"
    if claim.detects:
        entry["detects"] = list(claim.detects)
    return entry


def ingest(
    source: Source,
    documents: Sequence[tuple[str, str]],
    *,
    ngram_threshold: int = DEFAULT_NGRAM_THRESHOLD,
) -> Iterator[IngestionSession]:
    """Open a session per ``(locator, text)`` document, closing each after use.

    Yields sessions so a caller can extract from each; every session is closed
    on the way out whether or not extraction succeeded, so no source text
    outlives the loop.
    """
    for locator, text in documents:
        session = IngestionSession(
            source, text, locator=locator, ngram_threshold=ngram_threshold
        )
        try:
            yield session
        finally:
            session.close()
