"""Tests for the ingestion pipeline.

The pipeline's whole claim is "ingest, do not retain". These tests hold it to
that: the text is unreachable after the session closes, and a claim that
reproduces its source rather than restating it is rejected.
"""

from __future__ import annotations

import pytest

from src.knowledge import load_knowledge
from src.knowledge.ingest import (
    DEFAULT_NGRAM_THRESHOLD,
    ExtractedClaim,
    IngestionError,
    IngestionSession,
    SourceReceipt,
    VerbatimOverlapError,
    ingest,
    longest_shared_ngram,
    to_design_rule_yaml,
)
from src.knowledge.models import IngestionPolicy, Licence, Source, SourceTier

# A stand-in passage. Deliberately written here rather than copied from a real
# document — the test suite is not a place to smuggle in source text either.
PASSAGE = (
    "The minimum inside bend radius for cold formed sheet is governed by the "
    "ductility of the outer fibre, which is placed in tension during forming. "
    "Where the radius is too small for the temper, the outer surface will crack. "
    "Bending across the rolling direction tolerates a smaller radius than "
    "bending along it."
)


@pytest.fixture(scope="module")
def kb():
    return load_knowledge()


@pytest.fixture
def proprietary_source():
    return Source(
        source_id="test_proprietary",
        tier=SourceTier.HANDBOOK,
        title="A licensed handbook",
        publisher="Someone",
        designation="TEST-1",
        scope="testing",
        licence=Licence.PROPRIETARY,
        ingestion=IngestionPolicy.FACTS_ONLY,
    )


@pytest.fixture
def public_domain_source():
    return Source(
        source_id="test_public",
        tier=SourceTier.HANDBOOK,
        title="A government handbook",
        publisher="A government",
        designation="TEST-2",
        scope="testing",
        licence=Licence.PUBLIC_DOMAIN,
        licence_note="test fixture",
        ingestion=IngestionPolicy.FULL,
    )


# ── overlap detection ────────────────────────────────────────────────────────


def test_longest_shared_ngram_finds_the_run():
    claim = "the ductility of the outer fibre which is placed in tension governs it"
    overlap = longest_shared_ngram(PASSAGE, claim)
    assert "ductility of the outer fibre" in overlap


def test_overlap_ignores_case_and_punctuation():
    """Reproducing a sentence with the commas moved is still reproducing it."""
    claim = "THE DUCTILITY, OF THE OUTER FIBRE; WHICH IS PLACED IN TENSION!"
    overlap = longest_shared_ngram(PASSAGE, claim)
    assert len(overlap.split()) >= DEFAULT_NGRAM_THRESHOLD


def test_no_overlap_on_genuine_restatement():
    claim = "Tighter radii crack the outside of a bend because that surface stretches."
    overlap = longest_shared_ngram(PASSAGE, claim)
    assert len(overlap.split()) < DEFAULT_NGRAM_THRESHOLD


def test_overlap_handles_empty_input():
    assert longest_shared_ngram("", "anything") == ""
    assert longest_shared_ngram("anything", "") == ""


# ── retention: the text does not survive the session ─────────────────────────


def test_text_is_unreachable_after_close(proprietary_source):
    with IngestionSession(proprietary_source, PASSAGE, locator="p. 1") as session:
        assert session.text
    with pytest.raises(IngestionError, match="discarded"):
        _ = session.text


def test_receipt_survives_the_session(proprietary_source):
    with IngestionSession(proprietary_source, PASSAGE, locator="p. 214") as session:
        receipt = session.receipt
    assert receipt.source_id == "test_proprietary"
    assert receipt.locator == "p. 214"
    assert len(receipt.sha256) == 64
    assert receipt.word_count > 0


def test_receipt_identifies_the_document_without_keeping_it():
    """Same document, same hash; different document, different hash."""
    first = SourceReceipt.of("s", PASSAGE, "p. 1")
    same = SourceReceipt.of("s", PASSAGE, "p. 1")
    other = SourceReceipt.of("s", PASSAGE + " Revised.", "p. 1")
    assert first.sha256 == same.sha256
    assert first.sha256 != other.sha256


def test_ingest_closes_every_session(proprietary_source):
    sessions = list(ingest(proprietary_source, [("p. 1", PASSAGE), ("p. 2", PASSAGE)]))
    assert len(sessions) == 2
    for session in sessions:
        with pytest.raises(IngestionError):
            _ = session.text


def test_session_closes_even_when_extraction_raises(proprietary_source):
    generator = ingest(proprietary_source, [("p. 1", PASSAGE)])
    session = next(generator)
    with pytest.raises(RuntimeError):
        generator.throw(RuntimeError("extraction blew up"))
    with pytest.raises(IngestionError):
        _ = session.text


# ── the restatement guard ────────────────────────────────────────────────────


def test_verbatim_claim_is_rejected(proprietary_source):
    with IngestionSession(proprietary_source, PASSAGE) as session:
        with pytest.raises(VerbatimOverlapError):
            session.claim(
                statement=(
                    "the ductility of the outer fibre which is placed in tension "
                    "during forming"
                ),
                why="because it stretches",
            )


def test_restated_claim_is_accepted(proprietary_source):
    with IngestionSession(proprietary_source, PASSAGE) as session:
        claim = session.claim(
            statement="Default the inside bend radius to one material thickness.",
            why=(
                "The outside of a bend stretches, and past the temper's forming "
                "limit it splits. Grain direction moves that limit."
            ),
            metric="bend_radius_over_thickness",
            value_min=0.5,
            value_typical=1.0,
            units="ratio",
            processes=("sheet_metal",),
        )
    assert isinstance(claim, ExtractedClaim)
    assert claim.receipt.source_id == "test_proprietary"


def test_the_why_is_checked_too(proprietary_source):
    """A paraphrased headline with the source's own explanation under it."""
    with IngestionSession(proprietary_source, PASSAGE) as session:
        with pytest.raises(VerbatimOverlapError):
            session.claim(
                statement="Bend radius has a floor.",
                why=(
                    "the ductility of the outer fibre which is placed in tension "
                    "during forming"
                ),
            )


def test_public_domain_source_may_be_quoted(public_domain_source):
    """Where the licence permits it, quoting is legitimate."""
    with IngestionSession(public_domain_source, PASSAGE) as session:
        claim = session.claim(
            statement="Minimum bend radius depends on temper and grain direction.",
            why="The outer fibre is in tension and cracks past its forming limit.",
            verbatim_quote="Bending across the rolling direction tolerates a smaller radius",
        )
    assert claim.verbatim_quote


def test_quoting_a_facts_only_source_is_rejected(proprietary_source):
    with IngestionSession(proprietary_source, PASSAGE) as session:
        with pytest.raises(IngestionError, match="verbatim quote may not be retained"):
            session.claim(
                statement="Something restated entirely differently here.",
                why="A wholly independent explanation of the mechanism.",
                verbatim_quote="the ductility of the outer fibre",
            )


def test_reference_only_source_cannot_be_opened():
    source = Source(
        source_id="test_reference",
        tier=SourceTier.STANDARD,
        title="A standard we have not bought",
        publisher="A body",
        designation="TEST-3",
        scope="testing",
        ingestion=IngestionPolicy.REFERENCE_ONLY,
    )
    with pytest.raises(IngestionError, match="reference_only"):
        IngestionSession(source, PASSAGE)


# ── claim validity ───────────────────────────────────────────────────────────


def test_claim_without_why_is_rejected(proprietary_source):
    with IngestionSession(proprietary_source, PASSAGE) as session:
        with pytest.raises(IngestionError, match="no `why`"):
            session.claim(statement="Some assertion nobody explained.", why="  ")


def test_claim_with_value_needs_metric_and_units(proprietary_source):
    with IngestionSession(proprietary_source, PASSAGE) as session:
        with pytest.raises(IngestionError, match="metric and units"):
            session.claim(
                statement="A wholly independent assertion about radii.",
                why="An independent explanation of why that is so.",
                value_typical=1.0,
            )


def test_empty_source_is_rejected(proprietary_source):
    with pytest.raises(IngestionError, match="no text"):
        IngestionSession(proprietary_source, "   ")


# ── the output ───────────────────────────────────────────────────────────────


def test_rendered_rule_matches_the_corpus_schema(proprietary_source):
    with IngestionSession(proprietary_source, PASSAGE) as session:
        claim = session.claim(
            statement="Default the inside bend radius to one material thickness.",
            why="The outside of a bend stretches and splits past the forming limit.",
            metric="bend_radius_over_thickness",
            value_min=0.5,
            value_typical=1.0,
            units="ratio",
            processes=("sheet_metal",),
            detects=("TIGHT_BEND_RADIUS",),
        )

    entry = to_design_rule_yaml(
        claim,
        rule_id="TEST_BEND_RADIUS",
        tier="handbook",
        category="geometry",
        title="Minimum inside bend radius",
    )
    # The same required keys the corpus loader enforces on a real rule.
    for key in ("rule_id", "processes", "category", "title", "statement", "why",
                "relation", "source_id", "tier", "metric", "units"):
        assert key in entry, key
    assert entry["relation"] == "min"
    assert entry["source_id"] == "test_proprietary"
    # The source text is nowhere in the output.
    assert "outer fibre" not in str(entry)


def test_pipeline_output_carries_no_source_text(proprietary_source):
    """The end-to-end property: knowledge out, text nowhere."""
    with IngestionSession(proprietary_source, PASSAGE) as session:
        session.claim(
            statement="Bend radius floors follow from temper and grain direction.",
            why="Stretching the outside of a bend past its limit splits it.",
        )
        claims = session.claims

    rendered = " ".join(f"{c.statement} {c.why}" for c in claims)
    assert longest_shared_ngram(PASSAGE, rendered).split().__len__() < DEFAULT_NGRAM_THRESHOLD


def test_real_corpus_sources_can_drive_the_pipeline(kb):
    """The pipeline works against the actual registry, not just fixtures."""
    public = kb.sources["doe_hdbk_1017"]
    assert public.ingestion is IngestionPolicy.FULL
    with IngestionSession(public, PASSAGE, locator="vol. 1 §2") as session:
        assert session.receipt.locator == "vol. 1 §2"

    licensed = kb.sources["machinerys_handbook"]
    assert licensed.ingestion is IngestionPolicy.FACTS_ONLY
    with IngestionSession(licensed, PASSAGE) as session:
        with pytest.raises(IngestionError):
            session.claim(
                statement="An independent restatement of something.",
                why="An independent explanation.",
                verbatim_quote="the ductility of the outer fibre",
            )
