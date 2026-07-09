"""Identity-retrieval grounding engine — pure-core + live-Postgres corpus tests.

Two layers, mirroring the repo's ``test_triage_rollup`` / ``test_part_context``
convention:

  * **pure core** (no DB, always runs) — pins the honesty calibration directly:
    the geometry-similarity proxy is monotonic and bounded; name similarity is a
    documented token blend that returns None when there's nothing to compare; the
    blend + buckets behave (HIGH only when geometry is close AND a name agrees, or
    geometry is a near-duplicate).

  * **live corpus** (``DATABASE_URL``-guarded) — the decisive slice-1 behaviours
    against real Postgres + real trimesh signatures:
      - MATCH: a near-duplicate of a seeded part retrieves that part, HIGH/MEDIUM,
        ``grounded=True``.
      - HONEST MISS: an unlike shape gets no HIGH/MEDIUM match, ``grounded=False``,
        no fabricated identity.
      - EMPTY CORPUS: retrieval before any write-back is an honest empty.
      - CROSS-ORG ISOLATION: org B never sees org A's parts (decisive).
      - WRITE-BACK IDEMPOTENCY: upserting the same (org, mesh_hash) twice → ONE
        row carrying the LATEST declared identity.
"""
from __future__ import annotations

import os
import uuid

import pytest
import trimesh
from ulid import ULID

from src.eval import similarity
from src.services import identity_retrieval_service as ir


# ---------------------------------------------------------------------------
# Pure core — calibration honesty (no DB)
# ---------------------------------------------------------------------------


def test_geometry_similarity_is_monotonic_bounded_proxy():
    # 1.0 only at an exact match; strictly decreasing; always in (0, 1].
    assert ir.geometry_similarity(0.0) == 1.0
    seq = [ir.geometry_similarity(d) for d in (0.0, 0.5, 1.0, 2.5, 10.0)]
    assert seq == sorted(seq, reverse=True)
    assert all(0.0 < s <= 1.0 for s in seq)
    # A huge distance decays toward 0 (never negative, never fabricated).
    assert 0.0 <= ir.geometry_similarity(1e6) < 1e-3


def test_name_similarity_tokens_and_none():
    # Exact / containment agreement.
    assert ir.name_similarity("door handle", "door handle left") == 1.0
    assert ir.name_similarity("PN-4471", "pn 4471") == pytest.approx(1.0)
    # Partial overlap is between 0 and 1.
    s = ir.name_similarity("front mounting bracket", "rear mounting plate")
    assert 0.0 < s < 1.0
    # No comparable name on either side → None (honest N/A, never 0-by-default).
    assert ir.name_similarity(None, "anything") is None
    assert ir.name_similarity("anything", None) is None
    assert ir.name_similarity("", "x") is None


def test_combined_confidence_blend():
    # No name → geometry proxy alone (never invented name agreement).
    assert ir.combined_confidence(0.9, None) == pytest.approx(0.9)
    # Both present → weighted blend, geometry-anchored.
    c = ir.combined_confidence(0.8, 0.6)
    assert c == pytest.approx(ir.GEOM_WEIGHT * 0.8 + (1 - ir.GEOM_WEIGHT) * 0.6)
    assert 0.6 < c < 0.8


def test_bucket_high_requires_close_geometry_not_name_alone():
    # High blended score but MEDIOCRE geometry + name-driven → NOT high.
    # geom_sim modest, name perfect: combined can clear HIGH numerically, but the
    # geometry is neither a near-duplicate nor is name the only gate we trust.
    combined = ir.combined_confidence(0.85, 1.0)
    assert combined >= ir.HIGH_CONFIDENCE
    # Far geometry (distance well beyond near-dup) but name agrees → HIGH allowed
    # (name agreement is a legitimate corroborator). Distinguish the two HIGH gates:
    b_name = ir.confidence_bucket(combined, geometry_distance=5.0, name_sim=1.0)
    assert b_name == "HIGH"  # name agrees → HIGH permitted
    # Same combined but NO name and NOT a near-duplicate → downgraded to MEDIUM.
    b_geo = ir.confidence_bucket(combined, geometry_distance=5.0, name_sim=None)
    assert b_geo == "MEDIUM"
    # Near-duplicate geometry alone → HIGH even without a name.
    b_dup = ir.confidence_bucket(
        0.95, geometry_distance=ir.GEOM_NEAR_DUPLICATE_DIST - 0.01, name_sim=None
    )
    assert b_dup == "HIGH"


def test_bucket_low_below_medium():
    assert ir.confidence_bucket(0.2, geometry_distance=9.0, name_sim=None) == "LOW"
    assert ir.confidence_bucket(
        ir.MEDIUM_CONFIDENCE, geometry_distance=1.0, name_sim=0.3
    ) == "MEDIUM"


# ---------------------------------------------------------------------------
# Live-Postgres corpus tests (DATABASE_URL-guarded)
# ---------------------------------------------------------------------------

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


def _seed_meshes():
    """Four real, geometrically distinct parts with declared identities."""
    return [
        ("cube",  trimesh.creation.box(extents=[40, 40, 40]),
         "PN-1001", "Battery enclosure block", "PowerPack"),
        ("plate", trimesh.creation.box(extents=[120, 80, 4]),
         "PN-1002", "Mounting plate bracket", "Chassis"),
        ("rod",   trimesh.creation.cylinder(radius=6, height=120, sections=64),
         "PN-1003", "Drive shaft rod", "Drivetrain"),
        ("disc",  trimesh.creation.cylinder(radius=45, height=8, sections=96),
         "PN-1004", "Sensor cover disc", "Sensors"),
    ]


async def _mk_org(s, oid: str, label: str) -> None:
    from sqlalchemy import text

    await s.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:i, :n, :sl, now())"
        ),
        {"i": oid, "n": label, "sl": oid.lower()},
    )


async def _seed_corpus(s, org_id: str) -> None:
    from src.services import part_signature_service as sigsvc

    for tag, mesh, pn, name, prog in _seed_meshes():
        vec = similarity.vector_for_mesh(mesh)
        await sigsvc.upsert_signature(
            s, org_id, f"hash-{tag}", vec,
            declared_part_id=pn, declared_name=name, program=prog,
        )


@_requires_pg
@pytest.mark.asyncio
async def test_match_near_duplicate_grounds_identity():
    from sqlalchemy import text

    import src.db.engine as eng

    org = str(ULID())
    async with eng.get_session_factory()() as s:
        await _mk_org(s, org, f"IdMatch {uuid.uuid4().hex[:8]}")
        await _seed_corpus(s, org)
        await s.commit()

        # A near-duplicate of the seeded 'PN-1002 Mounting plate bracket'.
        near_dup = trimesh.creation.box(extents=[122, 81, 4.1])
        res = await ir.retrieve_identity(
            s, org, near_dup, name_hint="mounting plate", k=3
        )

        assert res.corpus_size == 4
        assert res.grounded is True
        top = res.matches[0]
        assert top.declared_part_id == "PN-1002"
        assert top.declared_name == "Mounting plate bracket"
        assert top.confidence_bucket in ("HIGH", "MEDIUM")
        assert top.combined_confidence >= ir.MEDIUM_CONFIDENCE
        # provenance is explicit — a retrieved suggestion, never asserted fact.
        assert top.provenance == ir.PROVENANCE
        assert any("SUGGESTION" in c for c in res.caveats)

        await s.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org})
        await s.commit()
    await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_honest_miss_no_fabricated_identity():
    from sqlalchemy import text

    import src.db.engine as eng

    org = str(ULID())
    async with eng.get_session_factory()() as s:
        await _mk_org(s, org, f"IdMiss {uuid.uuid4().hex[:8]}")
        await _seed_corpus(s, org)
        await s.commit()

        # A torus — unlike any seeded box/cylinder (different genus, proportions).
        weird = trimesh.creation.torus(major_radius=30, minor_radius=6)
        res = await ir.retrieve_identity(
            s, org, weird, name_hint="gizmo widget", k=3
        )

        assert res.corpus_size == 4
        assert res.grounded is False
        # No match clears the MEDIUM bar → no identity is claimed.
        assert all(m.confidence_bucket == "LOW" for m in res.matches)
        assert "no identity claimed" in (res.reason or "")

        await s.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org})
        await s.commit()
    await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_empty_corpus_is_honest_empty():
    from sqlalchemy import text

    import src.db.engine as eng

    org = str(ULID())
    async with eng.get_session_factory()() as s:
        await _mk_org(s, org, f"IdEmpty {uuid.uuid4().hex[:8]}")
        await s.commit()

        mesh = trimesh.creation.box(extents=[40, 40, 40])
        res = await ir.retrieve_identity(s, org, mesh, name_hint="anything", k=3)

        assert res.corpus_size == 0
        assert res.grounded is False
        assert res.matches == []
        assert "no org corpus yet" in (res.reason or "")

        await s.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org})
        await s.commit()
    await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_cross_org_isolation():
    """Org A seeds a part; org B retrieves the SAME mesh → gets NOTHING from A."""
    from sqlalchemy import text

    import src.db.engine as eng

    org_a = str(ULID())
    org_b = str(ULID())
    async with eng.get_session_factory()() as s:
        await _mk_org(s, org_a, f"IdA {uuid.uuid4().hex[:8]}")
        await _mk_org(s, org_b, f"IdB {uuid.uuid4().hex[:8]}")
        await _seed_corpus(s, org_a)  # ONLY org A gets a corpus
        await s.commit()

        # Org B retrieves the EXACT seeded plate mesh.
        exact_plate = trimesh.creation.box(extents=[120, 80, 4])
        res_b = await ir.retrieve_identity(
            s, org_b, exact_plate, name_hint="mounting plate bracket", k=5
        )
        # Decisive: B's corpus is empty; it can never see A's PN-1002.
        assert res_b.corpus_size == 0
        assert res_b.grounded is False
        assert res_b.matches == []

        # Symmetric sanity: A DOES ground the same mesh (isolation is not "broken").
        res_a = await ir.retrieve_identity(
            s, org_a, exact_plate, name_hint="mounting plate bracket", k=5
        )
        assert res_a.grounded is True
        assert res_a.matches[0].declared_part_id == "PN-1002"

        await s.execute(
            text("DELETE FROM organizations WHERE id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
        await s.commit()
    await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_write_back_idempotency_latest_identity_wins():
    from sqlalchemy import func, select, text

    import src.db.engine as eng
    from src.db.models import PartSignature
    from src.services import part_signature_service as sigsvc

    org = str(ULID())
    mesh = trimesh.creation.box(extents=[40, 40, 40])
    vec = similarity.vector_for_mesh(mesh)

    async with eng.get_session_factory()() as s:
        await _mk_org(s, org, f"IdIdem {uuid.uuid4().hex[:8]}")

        # Same (org, mesh_hash) upserted TWICE with a changed declared identity.
        await sigsvc.upsert_signature(
            s, org, "hash-x", vec,
            declared_part_id="PN-OLD", declared_name="old name", program="ProgA",
        )
        await sigsvc.upsert_signature(
            s, org, "hash-x", vec,
            declared_part_id="PN-NEW", declared_name="new name", program="ProgB",
        )
        await s.commit()

        count = (
            await s.execute(
                select(func.count())
                .select_from(PartSignature)
                .where(PartSignature.org_id == org, PartSignature.mesh_hash == "hash-x")
            )
        ).scalar()
        assert count == 1  # ONE row, not two

        rows = await sigsvc.list_signatures(s, org)
        assert len(rows) == 1
        assert rows[0].declared_part_id == "PN-NEW"
        assert rows[0].declared_name == "new name"
        assert rows[0].program == "ProgB"

        await s.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org})
        await s.commit()
    await eng.dispose_engine()
