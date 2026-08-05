"""Tests for the knowledge corpus.

The corpus makes one promise above all others: every claim it can put in front
of a user resolves to a real source. These tests enforce that promise, and the
supporting contract rules from ``src/knowledge/README.md``.
"""

from __future__ import annotations

import pytest
import yaml

from src.analysis.models import ProcessType
from src.knowledge import (
    KnowledgeValidationError,
    load_knowledge,
    library_documents,
)
from src.knowledge.loader import PACKS_DIR, _load_design_rules, _load_sources
from src.knowledge.models import FindingSeverity, Relation, SourceTier


@pytest.fixture(scope="module")
def kb():
    return load_knowledge(force_reload=True)


# ── the corpus contract ──────────────────────────────────────────────────────


def test_corpus_loads(kb):
    assert kb.sources
    assert kb.design_rules
    assert kb.environments
    assert kb.checklists
    assert kb.red_flags
    assert kb.glossary


def test_no_orphan_citations(kb):
    """Every record resolves to a source in the registry — the core promise."""
    known = set(kb.sources)
    for rule in kb.design_rules:
        assert rule.source.source_id in known, rule.rule_id
    for env in kb.environments.values():
        assert env.source.source_id in known, env.env_id
    for checklist in kb.checklists.values():
        assert checklist.source.source_id in known, checklist.checklist_id
    for flag in kb.red_flags:
        assert flag.source.source_id in known, flag.flag_id
    for term in kb.glossary:
        assert term.source.source_id in known, term.term


def test_every_rule_explains_itself(kb):
    """A rule with no `why` cannot be defended to an auditor or narrated."""
    for rule in kb.design_rules:
        assert rule.why.strip(), rule.rule_id


def test_every_numeric_rule_carries_units(kb):
    """A bare number with no unit is exactly the ambiguity this corpus exists to remove."""
    for rule in kb.design_rules:
        has_value = any(
            v is not None
            for v in (rule.value_min, rule.value_typical, rule.value_max)
        )
        if has_value:
            assert rule.units, f"{rule.rule_id} has values but no units"
            assert rule.metric, f"{rule.rule_id} has values but no metric"


def test_advisory_rules_carry_no_thresholds(kb):
    """An advisory rule must not smuggle in a threshold nobody can defend."""
    for rule in kb.design_rules:
        if rule.relation is Relation.ADVISORY:
            assert rule.value_min is None, rule.rule_id
            assert rule.value_max is None, rule.rule_id


def test_band_rules_are_ordered(kb):
    for rule in kb.design_rules:
        if rule.relation is Relation.BAND:
            assert rule.value_min is not None, rule.rule_id
            assert rule.value_max is not None, rule.rule_id
            assert rule.value_min <= rule.value_max, rule.rule_id
            if rule.value_typical is not None:
                assert rule.value_min <= rule.value_typical <= rule.value_max, (
                    rule.rule_id
                )


def test_every_red_flag_has_an_observable_tell(kb):
    """A red flag with no signal is an opinion, not a detector."""
    for flag in kb.red_flags:
        assert flag.signal.strip(), flag.flag_id
        assert flag.correct_form.strip(), flag.flag_id


def test_contested_sources_record_the_disagreement(kb):
    """`contested` is honest only if it says who disagrees about what."""
    contested = [s for s in kb.sources.values() if s.tier is SourceTier.CONTESTED]
    assert contested, "expected at least one contested source"
    for source in contested:
        assert source.disagreement, source.source_id


def test_contested_rules_are_reachable(kb):
    """Contested rules surface distinctly — they are the first to replace with shop data."""
    contested = kb.contested_rules()
    assert contested
    assert all(r.tier is SourceTier.CONTESTED for r in contested)


# ── coverage against the engine's own vocabulary ─────────────────────────────


def test_rules_reference_only_real_processes(kb):
    """A rule aimed at a process the engine does not model is dead knowledge."""
    valid = {pt.value for pt in ProcessType} | {"all"}
    for rule in kb.design_rules:
        unknown = set(rule.processes) - valid
        assert not unknown, f"{rule.rule_id} references unknown processes {unknown}"


def test_checklists_reference_only_real_processes(kb):
    valid = {pt.value for pt in ProcessType} | {"all"}
    for checklist in kb.checklists.values():
        unknown = set(checklist.applies_to) - valid
        assert not unknown, f"{checklist.checklist_id} references {unknown}"


def test_every_process_family_has_design_rules(kb):
    """Each of the three families must carry more than the universal rules."""
    families = {
        "additive": ["dmls", "fdm", "binder_jetting"],
        "subtractive": ["cnc_3axis", "cnc_turning", "wire_edm"],
        "formative": ["injection_molding", "sand_casting", "sheet_metal", "forging"],
    }
    for family, processes in families.items():
        for process in processes:
            specific = [
                r for r in kb.rules_for(process) if not r.universal
            ]
            assert specific, f"no process-specific rules for {process} ({family})"


def test_universal_rules_apply_everywhere(kb):
    for pt in ProcessType:
        rules = kb.rules_for(pt.value)
        assert any(r.universal for r in rules), pt.value


# ── lookups the engine and copilot will actually call ────────────────────────


def test_rules_backing_an_issue_code(kb):
    """The bridge from a DFM finding to the knowledge behind its threshold."""
    backing = kb.rules_backing("THIN_WALL")
    assert backing
    for rule in backing:
        assert "THIN_WALL" in rule.detects
        assert rule.citation.standard


def test_rule_citation_names_the_rule(kb):
    rule = kb.rule("AM_OVERHANG_ANGLE")
    assert rule is not None
    assert rule.citation.rule_id == "AM_OVERHANG_ANGLE"
    assert rule.citation.standard


def test_sour_service_environment_constraints(kb):
    """The 22 HRC ceiling is the constraint the oil & gas rule pack leans on."""
    env = kb.environment("sour_service_nace")
    assert env is not None
    assert env.max_hardness_hrc == 22.0
    assert "nace_mr0175" in env.requires_flags
    assert env.damage_mechanisms
    assert env.auditor_focus


def test_environment_hardness_gate_is_honest_about_unknowns(kb):
    """Unknown hardness returns None — never a silent pass."""
    env = kb.environment("sour_service_nace")
    assert env.admits_hardness(20.0) is True
    assert env.admits_hardness(30.0) is False
    assert env.admits_hardness(None) is None

    unconstrained = kb.environment("erosive_slurry")
    assert unconstrained.admits_hardness(60.0) is None


def test_checklists_expose_majors(kb):
    checklist = kb.checklist("api_6a_psl3")
    assert checklist is not None
    assert checklist.majors
    for item in checklist.majors:
        assert item.severity_if_missing is FindingSeverity.MAJOR
        assert item.evidence_expected
        assert item.classic_finding


def test_checklists_for_process(kb):
    """A machined oil & gas part picks up both the universal and API checklists."""
    found = {c.checklist_id for c in kb.checklists_for("cnc_5axis")}
    assert "universal_design_evidence" in found
    assert "api_6a_psl3" in found


def test_glossary_lookup_is_case_insensitive(kb):
    assert kb.define("should-cost") is not None
    assert kb.define("SHOULD-COST") is not None
    assert kb.define("  Should-Cost  ") is not None
    assert kb.define("not a real term") is None


def test_glossary_flags_common_confusions(kb):
    """The misunderstanding is usually the expensive part — most terms carry one."""
    with_confusion = [t for t in kb.glossary if t.common_confusion]
    assert len(with_confusion) >= len(kb.glossary) * 0.8


def test_red_flags_span_categories(kb):
    for category in ("geometry", "definition", "model", "compliance", "economics"):
        assert kb.red_flags_in(category), category


# ── the library ──────────────────────────────────────────────────────────────


def test_library_documents_present():
    docs = library_documents()
    assert docs, "the written library is empty"
    sections = {d.parent.name for d in docs}
    for expected in ("foundations", "processes", "cad", "audit", "exemplars"):
        assert expected in sections, f"library missing {expected}/"


def test_library_documents_have_front_matter():
    """Every library doc declares what it is and where its claims come from."""
    for doc in library_documents():
        text = doc.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{doc.name} has no front matter"
        front = yaml.safe_load(text.split("---", 2)[1])
        assert front.get("title"), doc.name
        assert front.get("domain"), doc.name
        assert front.get("sources"), doc.name


def test_library_front_matter_sources_resolve(kb):
    """A document citing an unregistered source is an unsourced claim."""
    for doc in library_documents():
        front = yaml.safe_load(doc.read_text(encoding="utf-8").split("---", 2)[1])
        for source_id in front.get("sources", []):
            assert source_id in kb.sources, f"{doc.name} cites unknown {source_id!r}"


# ── validation actually fails ────────────────────────────────────────────────


def test_dangling_source_id_is_rejected():
    """The contract is enforced, not merely documented."""
    sources = _load_sources()
    raw = yaml.safe_load((PACKS_DIR / "design_rules.yaml").read_text(encoding="utf-8"))
    raw["rules"][0]["source_id"] = "no_such_source"

    import src.knowledge.loader as loader_mod

    original = loader_mod._read
    loader_mod._read = lambda path: raw  # type: ignore[assignment]
    try:
        with pytest.raises(KnowledgeValidationError, match="unknown source_id"):
            _load_design_rules(sources)
    finally:
        loader_mod._read = original  # type: ignore[assignment]


def test_rule_without_why_is_rejected():
    sources = _load_sources()
    raw = yaml.safe_load((PACKS_DIR / "design_rules.yaml").read_text(encoding="utf-8"))
    raw["rules"][0].pop("why", None)

    import src.knowledge.loader as loader_mod

    original = loader_mod._read
    loader_mod._read = lambda path: raw  # type: ignore[assignment]
    try:
        with pytest.raises(KnowledgeValidationError, match="no `why`"):
            _load_design_rules(sources)
    finally:
        loader_mod._read = original  # type: ignore[assignment]


def test_load_is_cached():
    first = load_knowledge()
    second = load_knowledge()
    assert first is second
    assert load_knowledge(force_reload=True) is not first
