"""Load, validate and cache the knowledge corpus.

Validation is strict on the one thing that matters most: **no orphan citations**.
A rule, environment, checklist or red flag that references a ``source_id`` absent
from ``packs/sources.yaml`` raises :class:`KnowledgeValidationError` at load
time rather than surfacing an unsourced number to a user later. That is the
corpus contract enforced in code — see ``README.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from src.knowledge.models import (
    AuditChecklist,
    ChecklistItem,
    CurriculumModule,
    CurriculumTrack,
    DamageMechanism,
    DesignRule,
    Environment,
    FindingSeverity,
    GlossaryTerm,
    IngestionPolicy,
    KnowledgeBase,
    Licence,
    RedFlag,
    Relation,
    Source,
    SourceTier,
)

logger = logging.getLogger("cadverify.knowledge")

PACKS_DIR = Path(__file__).parent / "packs"
LIBRARY_DIR = Path(__file__).parent / "library"

_SOURCES_YAML = PACKS_DIR / "sources.yaml"
_DESIGN_RULES_YAML = PACKS_DIR / "design_rules.yaml"
_ENVIRONMENTS_YAML = PACKS_DIR / "environments.yaml"
_CHECKLISTS_YAML = PACKS_DIR / "audit_checklists.yaml"
_RED_FLAGS_YAML = PACKS_DIR / "red_flags.yaml"
_GLOSSARY_YAML = PACKS_DIR / "glossary.yaml"
_CURRICULUM_YAML = PACKS_DIR / "curriculum.yaml"

_CACHE: Optional[KnowledgeBase] = None


class KnowledgeValidationError(ValueError):
    """Raised when the corpus violates its own contract."""


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise KnowledgeValidationError(f"knowledge pack missing: {path.name}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise KnowledgeValidationError(f"{path.name} must parse to a mapping")
    return data


def _tuple(value: Any) -> tuple[str, ...]:
    """Coerce a possibly-absent YAML list into a tuple of strings."""
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _resolve(
    sources: dict[str, Source], source_id: Any, *, owner: str
) -> Source:
    """Resolve a ``source_id`` or fail loudly.

    The whole point of the corpus is that every claim is traceable. A dangling
    reference is a contract violation, not a warning.
    """
    if not source_id:
        raise KnowledgeValidationError(f"{owner} has no source_id")
    source = sources.get(str(source_id))
    if source is None:
        raise KnowledgeValidationError(
            f"{owner} cites unknown source_id {source_id!r}; "
            f"add it to packs/sources.yaml"
        )
    return source


def _tier(value: Any, *, owner: str) -> SourceTier:
    try:
        return SourceTier(str(value))
    except ValueError as exc:
        raise KnowledgeValidationError(
            f"{owner} has unknown tier {value!r}; "
            f"expected one of {[t.value for t in SourceTier]}"
        ) from exc


# ── individual pack parsers ──────────────────────────────────────────────────


_INGESTIBLE_LICENCES = {Licence.PUBLIC_DOMAIN, Licence.OPEN}


def _load_sources() -> dict[str, Source]:
    raw = _read(_SOURCES_YAML)
    sources: dict[str, Source] = {}
    for source_id, body in raw.items():
        if not isinstance(body, dict):
            raise KnowledgeValidationError(f"source {source_id!r} must be a mapping")
        owner = f"source {source_id!r}"

        try:
            licence = Licence(str(body.get("licence", Licence.PROPRIETARY.value)))
        except ValueError as exc:
            raise KnowledgeValidationError(
                f"{owner} has unknown licence {body.get('licence')!r}; "
                f"expected one of {[x.value for x in Licence]}"
            ) from exc

        try:
            ingestion = IngestionPolicy(
                str(body.get("ingestion", IngestionPolicy.FACTS_ONLY.value))
            )
        except ValueError as exc:
            raise KnowledgeValidationError(
                f"{owner} has unknown ingestion policy {body.get('ingestion')!r}; "
                f"expected one of {[x.value for x in IngestionPolicy]}"
            ) from exc

        # The guard that matters. Text may only be ingested when the licence
        # actually permits it — never because someone set the field hopefully.
        if ingestion is IngestionPolicy.FULL and licence not in _INGESTIBLE_LICENCES:
            raise KnowledgeValidationError(
                f"{owner} declares ingestion 'full' with licence {licence.value!r}. "
                f"Full text ingestion requires 'public_domain' or 'open'. "
                f"Facts may still be stated with attribution under 'facts_only'."
            )
        if licence in _INGESTIBLE_LICENCES and not body.get("licence_note"):
            raise KnowledgeValidationError(
                f"{owner} claims licence {licence.value!r} but gives no "
                f"`licence_note` explaining the basis. State why it is free to use."
            )

        sources[source_id] = Source(
            source_id=source_id,
            tier=_tier(body.get("tier"), owner=owner),
            title=str(body.get("title", "")),
            publisher=str(body.get("publisher", "")),
            designation=str(body.get("designation", source_id)),
            scope=str(body.get("scope", "")),
            edition=body.get("edition"),
            access=body.get("access"),
            caution=body.get("caution"),
            disagreement=body.get("disagreement"),
            licence=licence,
            ingestion=ingestion,
            licence_note=body.get("licence_note"),
        )
    if not sources:
        raise KnowledgeValidationError("sources.yaml defined no sources")
    return sources


def _load_design_rules(sources: dict[str, Source]) -> tuple[DesignRule, ...]:
    raw = _read(_DESIGN_RULES_YAML)
    rules: list[DesignRule] = []
    seen: set[str] = set()

    for entry in raw.get("rules", []):
        rule_id = str(entry.get("rule_id", ""))
        owner = f"design rule {rule_id!r}"
        if not rule_id:
            raise KnowledgeValidationError("a design rule is missing rule_id")
        if rule_id in seen:
            raise KnowledgeValidationError(f"duplicate rule_id {rule_id!r}")
        seen.add(rule_id)

        if not entry.get("why"):
            raise KnowledgeValidationError(
                f"{owner} has no `why`; a rule that cannot be explained "
                f"cannot be defended to an auditor"
            )

        try:
            relation = Relation(str(entry.get("relation", "advisory")))
        except ValueError as exc:
            raise KnowledgeValidationError(
                f"{owner} has unknown relation {entry.get('relation')!r}"
            ) from exc

        rules.append(
            DesignRule(
                rule_id=rule_id,
                processes=_tuple(entry.get("processes")),
                category=str(entry.get("category", "general")),
                title=str(entry.get("title", rule_id)),
                statement=str(entry.get("statement", "")),
                why=str(entry["why"]),
                relation=relation,
                source=_resolve(sources, entry.get("source_id"), owner=owner),
                tier=_tier(entry.get("tier"), owner=owner),
                metric=entry.get("metric"),
                value_min=entry.get("value_min"),
                value_typical=entry.get("value_typical"),
                value_max=entry.get("value_max"),
                units=entry.get("units"),
                good=entry.get("good"),
                bad=entry.get("bad"),
                detects=_tuple(entry.get("detects")),
            )
        )
    return tuple(rules)


def _load_environments(sources: dict[str, Source]) -> dict[str, Environment]:
    raw = _read(_ENVIRONMENTS_YAML)
    environments: dict[str, Environment] = {}

    for entry in raw.get("environments", []):
        env_id = str(entry.get("env_id", ""))
        owner = f"environment {env_id!r}"
        if not env_id:
            raise KnowledgeValidationError("an environment is missing env_id")
        if env_id in environments:
            raise KnowledgeValidationError(f"duplicate env_id {env_id!r}")

        constraints = entry.get("constraints") or {}
        mechanisms = tuple(
            DamageMechanism(
                mechanism_id=str(m.get("id", "")),
                name=str(m.get("name", "")),
                mechanism=str(m.get("mechanism", "")),
                design_response=str(m.get("design_response", "")),
            )
            for m in entry.get("damage_mechanisms", [])
        )

        environments[env_id] = Environment(
            env_id=env_id,
            name=str(entry.get("name", env_id)),
            family=str(entry.get("family", "general")),
            summary=str(entry.get("summary", "")),
            source=_resolve(sources, entry.get("source_id"), owner=owner),
            tier=_tier(entry.get("tier"), owner=owner),
            trigger=entry.get("trigger"),
            requires_flags=_tuple(constraints.get("requires_flags")),
            forbids_flags=_tuple(constraints.get("forbids_flags")),
            max_hardness_hrc=constraints.get("max_hardness_hrc"),
            min_service_temp_c=constraints.get("min_service_temp_c"),
            max_service_temp_c=constraints.get("max_service_temp_c"),
            damage_mechanisms=mechanisms,
            typical_compliant_materials=_tuple(entry.get("typical_compliant_materials")),
            typical_noncompliant_materials=_tuple(
                entry.get("typical_noncompliant_materials")
            ),
            design_notes=_tuple(entry.get("design_notes")),
            auditor_focus=entry.get("auditor_focus"),
        )
    return environments


def _load_checklists(sources: dict[str, Source]) -> dict[str, AuditChecklist]:
    raw = _read(_CHECKLISTS_YAML)
    checklists: dict[str, AuditChecklist] = {}

    for entry in raw.get("checklists", []):
        checklist_id = str(entry.get("checklist_id", ""))
        owner = f"checklist {checklist_id!r}"
        if not checklist_id:
            raise KnowledgeValidationError("a checklist is missing checklist_id")
        if checklist_id in checklists:
            raise KnowledgeValidationError(f"duplicate checklist_id {checklist_id!r}")

        items: list[ChecklistItem] = []
        for raw_item in entry.get("items", []):
            item_id = str(raw_item.get("id", ""))
            try:
                severity = FindingSeverity(
                    str(raw_item.get("severity_if_missing", "observation"))
                )
            except ValueError as exc:
                raise KnowledgeValidationError(
                    f"{owner} item {item_id!r} has unknown severity "
                    f"{raw_item.get('severity_if_missing')!r}"
                ) from exc
            items.append(
                ChecklistItem(
                    item_id=item_id,
                    trigger=str(raw_item.get("trigger", "")),
                    evidence_expected=str(raw_item.get("evidence_expected", "")),
                    classic_finding=str(raw_item.get("classic_finding", "")),
                    severity_if_missing=severity,
                    design_lever=raw_item.get("design_lever"),
                )
            )

        checklists[checklist_id] = AuditChecklist(
            checklist_id=checklist_id,
            name=str(entry.get("name", checklist_id)),
            regime=str(entry.get("regime", "")),
            mindset=str(entry.get("mindset", "")),
            source=_resolve(sources, entry.get("source_id"), owner=owner),
            tier=_tier(entry.get("tier"), owner=owner),
            applies_to=_tuple(entry.get("applies_to")),
            items=tuple(items),
        )
    return checklists


def _load_red_flags(sources: dict[str, Source]) -> tuple[RedFlag, ...]:
    raw = _read(_RED_FLAGS_YAML)
    flags: list[RedFlag] = []
    seen: set[str] = set()

    for entry in raw.get("red_flags", []):
        flag_id = str(entry.get("flag_id", ""))
        owner = f"red flag {flag_id!r}"
        if not flag_id:
            raise KnowledgeValidationError("a red flag is missing flag_id")
        if flag_id in seen:
            raise KnowledgeValidationError(f"duplicate flag_id {flag_id!r}")
        seen.add(flag_id)

        if not entry.get("signal"):
            raise KnowledgeValidationError(
                f"{owner} has no `signal`; a red flag with no observable tell "
                f"cannot become a detector"
            )

        flags.append(
            RedFlag(
                flag_id=flag_id,
                category=str(entry.get("category", "general")),
                name=str(entry.get("name", flag_id)),
                looks_like=str(entry.get("looks_like", "")),
                signal=str(entry["signal"]),
                why_bad=str(entry.get("why_bad", "")),
                cost_of_missing_it=str(entry.get("cost_of_missing_it", "")),
                correct_form=str(entry.get("correct_form", "")),
                source=_resolve(sources, entry.get("source_id"), owner=owner),
                tier=_tier(entry.get("tier"), owner=owner),
            )
        )
    return tuple(flags)


def _load_glossary(sources: dict[str, Source]) -> tuple[GlossaryTerm, ...]:
    raw = _read(_GLOSSARY_YAML)
    terms: list[GlossaryTerm] = []

    for entry in raw.get("terms", []):
        term = str(entry.get("term", ""))
        if not term:
            raise KnowledgeValidationError("a glossary entry is missing `term`")
        terms.append(
            GlossaryTerm(
                term=term,
                domain=str(entry.get("domain", "general")),
                definition=str(entry.get("definition", "")),
                source=_resolve(
                    sources, entry.get("source_id"), owner=f"glossary term {term!r}"
                ),
                common_confusion=entry.get("common_confusion"),
            )
        )
    return tuple(terms)


def _load_curriculum(
    known_record_ids: set[str],
) -> tuple[dict[str, CurriculumModule], dict[str, CurriculumTrack]]:
    """Load the curriculum and verify it stays anchored to the corpus.

    Two checks matter here. Prerequisites must form a DAG — a cycle means no
    valid learning order exists. And ``covers`` must name real corpus records,
    so a module cannot drift into describing knowledge the engine does not
    actually have.
    """
    raw = _read(_CURRICULUM_YAML)
    modules: dict[str, CurriculumModule] = {}

    for entry in raw.get("modules", []):
        module_id = str(entry.get("module_id", ""))
        owner = f"curriculum module {module_id!r}"
        if not module_id:
            raise KnowledgeValidationError("a curriculum module is missing module_id")
        if module_id in modules:
            raise KnowledgeValidationError(f"duplicate module_id {module_id!r}")

        for required in ("question", "understand", "misconception"):
            if not entry.get(required):
                raise KnowledgeValidationError(f"{owner} has no `{required}`")

        covers = _tuple(entry.get("covers"))
        unknown = set(covers) - known_record_ids
        if unknown:
            raise KnowledgeValidationError(
                f"{owner} claims to cover unknown records {sorted(unknown)}; "
                f"a module must stay anchored to records the engine has"
            )

        modules[module_id] = CurriculumModule(
            module_id=module_id,
            title=str(entry.get("title", module_id)),
            tier=int(entry.get("tier", 0)),
            question=str(entry["question"]),
            understand=str(entry["understand"]),
            misconception=str(entry["misconception"]),
            depends_on=_tuple(entry.get("depends_on")),
            reading=_tuple(entry.get("reading")),
            covers=covers,
        )

    # Prerequisites must resolve, and must not cycle.
    for module in modules.values():
        missing = set(module.depends_on) - set(modules)
        if missing:
            raise KnowledgeValidationError(
                f"module {module.module_id!r} depends on unknown "
                f"{sorted(missing)}"
            )

    _assert_acyclic(modules)

    tracks: dict[str, CurriculumTrack] = {}
    for entry in raw.get("tracks", []):
        track_id = str(entry.get("track_id", ""))
        if not track_id:
            raise KnowledgeValidationError("a curriculum track is missing track_id")
        if track_id in tracks:
            raise KnowledgeValidationError(f"duplicate track_id {track_id!r}")

        module_ids = _tuple(entry.get("modules"))
        unknown = set(module_ids) - set(modules)
        if unknown:
            raise KnowledgeValidationError(
                f"track {track_id!r} references unknown modules {sorted(unknown)}"
            )

        # A track that presents a module before its prerequisite teaches in an
        # order that cannot work.
        seen: set[str] = set()
        for module_id in module_ids:
            unmet = set(modules[module_id].depends_on) - seen
            if unmet:
                raise KnowledgeValidationError(
                    f"track {track_id!r} places {module_id!r} before its "
                    f"prerequisites {sorted(unmet)}"
                )
            seen.add(module_id)

        tracks[track_id] = CurriculumTrack(
            track_id=track_id,
            title=str(entry.get("title", track_id)),
            goal=str(entry.get("goal", "")),
            modules=module_ids,
        )

    return modules, tracks


def _assert_acyclic(modules: dict[str, CurriculumModule]) -> None:
    """Depth-first cycle detection over the prerequisite graph."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {module_id: WHITE for module_id in modules}

    def visit(module_id: str, path: list[str]) -> None:
        colour[module_id] = GREY
        for prerequisite in modules[module_id].depends_on:
            if colour[prerequisite] == GREY:
                cycle = " -> ".join(path + [module_id, prerequisite])
                raise KnowledgeValidationError(
                    f"curriculum prerequisites form a cycle: {cycle}"
                )
            if colour[prerequisite] == WHITE:
                visit(prerequisite, path + [module_id])
        colour[module_id] = BLACK

    for module_id in modules:
        if colour[module_id] == WHITE:
            visit(module_id, [])


# ── public API ───────────────────────────────────────────────────────────────


def load_knowledge(*, force_reload: bool = False) -> KnowledgeBase:
    """Load and cache the corpus.

    Args:
        force_reload: Re-read from disk instead of returning the cached
            instance. Used by tests and by any future hot-reload path.

    Raises:
        KnowledgeValidationError: The corpus violates its contract — a missing
            pack, a dangling ``source_id``, a rule with no ``why``, a red flag
            with no ``signal``, or a duplicate identifier.
    """
    global _CACHE
    if _CACHE is not None and not force_reload:
        return _CACHE

    sources = _load_sources()
    design_rules = _load_design_rules(sources)
    red_flags = _load_red_flags(sources)

    # The curriculum may only claim to cover records that actually exist.
    known_record_ids = {r.rule_id for r in design_rules} | {
        f.flag_id for f in red_flags
    }
    modules, tracks = _load_curriculum(known_record_ids)

    kb = KnowledgeBase(
        sources=sources,
        design_rules=design_rules,
        environments=_load_environments(sources),
        checklists=_load_checklists(sources),
        red_flags=red_flags,
        glossary=_load_glossary(sources),
        modules=modules,
        tracks=tracks,
    )

    logger.info(
        "knowledge corpus loaded: %d sources, %d rules, %d environments, "
        "%d checklists, %d red flags, %d terms",
        len(kb.sources),
        len(kb.design_rules),
        len(kb.environments),
        len(kb.checklists),
        len(kb.red_flags),
        len(kb.glossary),
    )

    _CACHE = kb
    return kb


def library_documents() -> tuple[Path, ...]:
    """Every written knowledge document, sorted.

    The markdown library is the human half of the corpus. Returned as paths so
    a caller can serve, index or embed them without this module taking a view
    on which.
    """
    if not LIBRARY_DIR.exists():
        return ()
    return tuple(sorted(LIBRARY_DIR.rglob("*.md")))
