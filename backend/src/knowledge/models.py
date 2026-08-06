"""Typed records for the knowledge corpus.

Every record that can back a user-visible statement exposes ``.citation``,
returning the same :class:`src.analysis.models.Citation` shape the DFM analyzers
already produce. That is deliberate: a knowledge-backed claim is then
inspectable in the UI through the mechanism that already exists for analyzer
citations, with no second provenance pathway to build or to trust.

Nothing in this corpus is ever MEASURED provenance. Every numeric value here is
a literature default that a real shop measurement must be able to override.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.analysis.models import Citation


class SourceTier(str, Enum):
    """How much authority a source carries.

    ``CONTESTED`` is a first-class outcome, not a defect: where reputable
    sources materially disagree, the corpus records the range and the
    disagreement rather than inventing a consensus.
    """

    STANDARD = "standard"
    VENDOR = "vendor"
    HANDBOOK = "handbook"
    PRACTICE = "practice"
    CONTESTED = "contested"


class Licence(str, Enum):
    """The copyright status of a source, which governs what may be done with it.

    This is deliberately separate from ``Source.access`` (whether the text costs
    money). A freely-readable standard is still copyrighted; a paid US
    Government document is still public domain. Price and licence are different
    questions and conflating them is how ingestion pipelines get built on
    material that cannot carry them.
    """

    PUBLIC_DOMAIN = "public_domain"  # e.g. US Government works (17 USC 105)
    OPEN = "open"                    # explicit open licence permitting reuse
    PROPRIETARY = "proprietary"      # all rights reserved
    UNKNOWN = "unknown"              # not yet determined — treated as proprietary


class IngestionPolicy(str, Enum):
    """What this corpus may do with a source.

    ``FACTS_ONLY`` is the default and covers almost everything here: a
    threshold value or a requirement is a fact, and facts are not copyrightable
    — but the expression is, and the act of machine-copying the text is
    reproduction regardless of how the output is later worded.
    """

    FULL = "full"                    # text may be ingested and stored
    FACTS_ONLY = "facts_only"        # state facts with attribution; never copy the text
    REFERENCE_ONLY = "reference_only"  # cite that it exists and what it requires; no content


class Relation(str, Enum):
    """How a rule's value constrains the measured feature."""

    MIN = "min"
    MAX = "max"
    RATIO_MAX = "ratio_max"
    RATIO_MIN = "ratio_min"
    BAND = "band"
    ADVISORY = "advisory"


class FindingSeverity(str, Enum):
    """Weight an auditor gives to a missing control."""

    OBSERVATION = "observation"
    MINOR = "minor"
    MAJOR = "major"


@dataclass(frozen=True)
class Source:
    """One entry in the citation registry (``packs/sources.yaml``).

    ``licence`` and ``ingestion`` default to the most restrictive values.
    Loosening them requires stating why in the YAML, which is the point: the
    safe default should be free and the permissive one should cost a decision.
    """

    source_id: str
    tier: SourceTier
    title: str
    publisher: str
    designation: str
    scope: str
    edition: Optional[str] = None
    access: Optional[str] = None
    caution: Optional[str] = None
    disagreement: Optional[str] = None
    licence: Licence = Licence.PROPRIETARY
    ingestion: IngestionPolicy = IngestionPolicy.FACTS_ONLY
    licence_note: Optional[str] = None

    @property
    def citation(self) -> Citation:
        """Render as the analyzers' ``Citation`` so the UI can inspect it."""
        return Citation(standard=self.designation, text=self.title)

    @property
    def may_ingest_text(self) -> bool:
        """Whether this source's text may be copied into the corpus.

        True only for public-domain and openly-licensed material. Everything
        else contributes attributed facts, never text.
        """
        return self.ingestion is IngestionPolicy.FULL


@dataclass(frozen=True)
class DesignRule:
    """One numeric or advisory design rule from ``packs/design_rules.yaml``."""

    rule_id: str
    processes: tuple[str, ...]
    category: str
    title: str
    statement: str
    why: str
    relation: Relation
    source: Source
    tier: SourceTier
    metric: Optional[str] = None
    value_min: Optional[float] = None
    value_typical: Optional[float] = None
    value_max: Optional[float] = None
    units: Optional[str] = None
    good: Optional[str] = None
    bad: Optional[str] = None
    detects: tuple[str, ...] = ()

    @property
    def universal(self) -> bool:
        """True when the rule applies to every process."""
        return "all" in self.processes

    def applies_to(self, process: str) -> bool:
        return self.universal or process in self.processes

    @property
    def citation(self) -> Citation:
        """A citation that names the rule as well as the source."""
        return Citation(
            standard=self.source.designation,
            text=self.statement,
            rule_id=self.rule_id,
        )


@dataclass(frozen=True)
class DamageMechanism:
    """A way the service environment attacks the part."""

    mechanism_id: str
    name: str
    mechanism: str
    design_response: str


@dataclass(frozen=True)
class Environment:
    """A declared service environment from ``packs/environments.yaml``.

    Backs "The Environment Door": the constraints narrow the candidate material
    set and say why. A narrowed set is never a compliance assertion.
    """

    env_id: str
    name: str
    family: str
    summary: str
    source: Source
    tier: SourceTier
    trigger: Optional[str] = None
    requires_flags: tuple[str, ...] = ()
    forbids_flags: tuple[str, ...] = ()
    max_hardness_hrc: Optional[float] = None
    min_service_temp_c: Optional[float] = None
    max_service_temp_c: Optional[float] = None
    damage_mechanisms: tuple[DamageMechanism, ...] = ()
    typical_compliant_materials: tuple[str, ...] = ()
    typical_noncompliant_materials: tuple[str, ...] = ()
    design_notes: tuple[str, ...] = ()
    auditor_focus: Optional[str] = None

    @property
    def citation(self) -> Citation:
        return Citation(standard=self.source.designation, text=self.summary)

    def admits_hardness(self, hardness_hrc: Optional[float]) -> Optional[bool]:
        """Does a material of this hardness pass the environment's ceiling?

        Returns ``None`` when the environment sets no hardness limit or the
        hardness is unknown — an honest "cannot say", never a default pass.
        """
        if self.max_hardness_hrc is None or hardness_hrc is None:
            return None
        return hardness_hrc <= self.max_hardness_hrc


@dataclass(frozen=True)
class ChecklistItem:
    """One thing an expert auditor actually opens."""

    item_id: str
    trigger: str
    evidence_expected: str
    classic_finding: str
    severity_if_missing: FindingSeverity
    design_lever: Optional[str] = None


@dataclass(frozen=True)
class AuditChecklist:
    """An audit regime's design-side checklist from ``packs/audit_checklists.yaml``."""

    checklist_id: str
    name: str
    regime: str
    mindset: str
    source: Source
    tier: SourceTier
    applies_to: tuple[str, ...] = ()
    items: tuple[ChecklistItem, ...] = ()

    def applies_to_process(self, process: str) -> bool:
        return "all" in self.applies_to or process in self.applies_to

    @property
    def majors(self) -> tuple[ChecklistItem, ...]:
        """Items whose absence puts product acceptance at risk."""
        return tuple(
            i for i in self.items if i.severity_if_missing is FindingSeverity.MAJOR
        )

    @property
    def citation(self) -> Citation:
        return Citation(standard=self.source.designation, text=self.regime)


@dataclass(frozen=True)
class RedFlag:
    """An anti-pattern from ``packs/red_flags.yaml`` — what bad looks like."""

    flag_id: str
    category: str
    name: str
    looks_like: str
    signal: str
    why_bad: str
    cost_of_missing_it: str
    correct_form: str
    source: Source
    tier: SourceTier

    @property
    def citation(self) -> Citation:
        return Citation(
            standard=self.source.designation,
            text=self.why_bad,
            rule_id=self.flag_id,
        )


@dataclass(frozen=True)
class GlossaryTerm:
    """A defined term, plus the misunderstanding that usually costs money."""

    term: str
    domain: str
    definition: str
    source: Source
    common_confusion: Optional[str] = None


@dataclass
class KnowledgeBase:
    """The loaded corpus. Built once and cached by :func:`load_knowledge`."""

    sources: dict[str, Source] = field(default_factory=dict)
    design_rules: tuple[DesignRule, ...] = ()
    environments: dict[str, Environment] = field(default_factory=dict)
    checklists: dict[str, AuditChecklist] = field(default_factory=dict)
    red_flags: tuple[RedFlag, ...] = ()
    glossary: tuple[GlossaryTerm, ...] = ()

    # ── lookups ──────────────────────────────────────────────────────────

    def rules_for(self, process: str) -> tuple[DesignRule, ...]:
        """Design rules applying to a process, universal rules included."""
        return tuple(r for r in self.design_rules if r.applies_to(process))

    def rule(self, rule_id: str) -> Optional[DesignRule]:
        return next((r for r in self.design_rules if r.rule_id == rule_id), None)

    def rules_backing(self, issue_code: str) -> tuple[DesignRule, ...]:
        """Rules that explain a given analyzer ``Issue.code``.

        This is the bridge from a DFM finding to the knowledge behind it: a
        finding can show not only *that* it fired but *why the threshold is
        what it is*, and cite the source.
        """
        return tuple(r for r in self.design_rules if issue_code in r.detects)

    def environment(self, env_id: str) -> Optional[Environment]:
        return self.environments.get(env_id)

    def checklist(self, checklist_id: str) -> Optional[AuditChecklist]:
        return self.checklists.get(checklist_id)

    def checklists_for(self, process: str) -> tuple[AuditChecklist, ...]:
        return tuple(
            c for c in self.checklists.values() if c.applies_to_process(process)
        )

    def red_flags_in(self, category: str) -> tuple[RedFlag, ...]:
        return tuple(f for f in self.red_flags if f.category == category)

    def define(self, term: str) -> Optional[GlossaryTerm]:
        """Case-insensitive glossary lookup."""
        needle = term.strip().casefold()
        return next((t for t in self.glossary if t.term.casefold() == needle), None)

    def ingestible_sources(self) -> tuple[Source, ...]:
        """Sources whose text may legitimately be ingested.

        The candidate set for any bulk-ingestion pipeline. Anything outside it
        contributes attributed facts only.
        """
        return tuple(s for s in self.sources.values() if s.may_ingest_text)

    def contested_rules(self) -> tuple[DesignRule, ...]:
        """Rules whose sources materially disagree.

        Worth surfacing distinctly: these are exactly the numbers a customer's
        own shop data should replace first.
        """
        return tuple(r for r in self.design_rules if r.tier is SourceTier.CONTESTED)
