#!/usr/bin/env python3
"""Deterministic fixture/oracle seam for WORK-06, WORK-08, and WORK-12.

The browser runner owns every user mutation. This helper only establishes the
pre-existing organization and cost evidence, then exposes read-only durable
snapshots for browser assertions. WORK-08 creates its retained CAD through the
real browser-to-worker cost-batch workflow.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from ulid import ULID

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import src.db.engine as eng
from src.auth.hashing import hash_password


def _estimate(
    process: str,
    material: str,
    quantity: int,
    unit_cost: float,
    *,
    validated: bool,
) -> dict[str, Any]:
    fixed = round(unit_cost * 0.2, 3)
    variable = round(unit_cost - fixed, 3)
    return {
        "process": process,
        "material": material,
        "quantity": quantity,
        "unit_cost_usd": unit_cost,
        "fixed_cost_usd": fixed,
        "variable_cost_usd": variable,
        "est_error_band_pct": 10,
        "confidence": {
            "low_usd": round(unit_cost * 0.9, 3),
            "high_usd": round(unit_cost * 1.1, 3),
            "half_width_pct": 10,
            "label": "measured-fixture" if validated else "assumption",
            "validated": validated,
            "basis": "pinned QA fixture",
        },
        "dfm_ready": True,
        "line_items": {
            "material": round(variable * 0.4, 3),
            "machine": round(variable * 0.6, 3),
            "setup": fixed,
        },
    }


def _cost_result(
    process: str,
    material: str,
    recommendations: dict[str, float],
    *,
    validated: bool,
) -> dict[str, Any]:
    first_quantity = min(int(quantity) for quantity in recommendations)
    first_cost = recommendations[str(first_quantity)]
    rec = {
        quantity: {
            "process": process,
            "material": material,
            "unit_cost_usd": value,
        }
        for quantity, value in recommendations.items()
    }
    return {
        "status": "completed",
        "reason": "Deterministic browser-matrix fixture.",
        "geometry": {
            "volume_cm3": 2.72,
            "surface_area_cm2": 14.32,
            "bbox_mm": [20, 15, 10],
            "watertight": True,
            "face_count": 6,
        },
        "material_class": material,
        "quantities": sorted(int(quantity) for quantity in recommendations),
        "routing": {
            "recommended_process": process,
            "archetype": "prismatic",
            "confidence": "high",
            "reasoning": "Pinned matrix fixture.",
        },
        "estimates": [
            _estimate(
                process,
                material,
                first_quantity,
                first_cost,
                validated=validated,
            )
        ],
        "decision": {
            "make_now_process": process,
            "make_now_material": material,
            "tooling_process": None,
            "tooling_dfm_ready": True,
            "crossover_qty": None,
            "recommendation": rec,
            "if_redesigned": {},
            "note": "Pinned compare and RFQ oracle.",
        },
        "engine_feasibility": [],
        "assumptions": [
            {
                "name": "fixture_source",
                "value": "WORK matrix",
                "unit": "",
                "source": "browser QA",
                "provenance": "MEASURED" if validated else "DEFAULT",
            }
        ],
        "notes": ["Durable test evidence; not a supplier quote."],
    }


async def seed(tag: str, password: str) -> dict[str, Any]:
    org_id = str(ULID())
    org_name = f"QA Compare RFQ Key Org {tag}"
    email = f"qa-work-matrix-{tag}@example.com"
    now = datetime.now(timezone.utc)
    specs = [
        {
            "key": "A",
            "filename": f"WORK-06-A-{tag}.step",
            "process": "cnc_3axis",
            "material": "aluminum",
            "recommendations": {"1": 10.0, "10": 20.0, "100": 8.0},
            "validated": True,
            "approval_status": "approved",
            "approved_at": now - timedelta(minutes=4),
            "stale_at": None,
            "stale_reason": None,
            "created_at": now - timedelta(minutes=5),
        },
        {
            "key": "B",
            "filename": f"WORK-06-B-{tag}.step",
            "process": "mjf",
            "material": "polymer",
            "recommendations": {"1": 12.346, "10": 15.0, "1000": 7.0},
            "validated": False,
            "approval_status": "approved",
            "approved_at": now - timedelta(minutes=3),
            "stale_at": now - timedelta(days=1),
            "stale_reason": "Governed fixture assumptions changed.",
            "created_at": now - timedelta(minutes=4),
        },
        {
            "key": "C",
            "filename": f"WORK-08-C-{tag}.step",
            "process": "dmls",
            "material": "titanium",
            "recommendations": {"1": 30.0},
            "validated": False,
            "approval_status": "unreviewed",
            "approved_at": None,
            "stale_at": None,
            "stale_reason": None,
            "created_at": now - timedelta(minutes=3),
        },
    ]
    output: dict[str, Any] = {
        "tag": tag,
        "org": {"id": org_id, "name": org_name},
        "owner": {"email": email},
        "decisions": {},
    }
    async with eng.get_session_factory()() as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id,name,slug,created_at) "
                "VALUES (:id,:name,:slug,now())"
            ),
            {
                "id": org_id,
                "name": org_name,
                "slug": f"qa-work-matrix-{tag}",
            },
        )
        owner_row = (
            await session.execute(
                text(
                    "INSERT INTO users "
                    "(email,email_lower,role,auth_provider,password_hash,current_org_id,"
                    "is_active,session_version) "
                    "VALUES (:email,:email,'analyst','password',:password_hash,:org,true,0) "
                    "RETURNING id"
                ),
                {
                    "email": email,
                    "password_hash": hash_password(password),
                    "org": org_id,
                },
            )
        ).first()
        owner_id = int(owner_row[0])
        await session.execute(
            text(
                "INSERT INTO memberships (id,org_id,user_id,org_role,created_at) "
                "VALUES (:id,:org,:user,'admin',now())"
            ),
            {"id": str(ULID()), "org": org_id, "user": owner_id},
        )
        output["owner"]["id"] = owner_id

        for spec in specs:
            result = _cost_result(
                spec["process"],
                spec["material"],
                spec["recommendations"],
                validated=spec["validated"],
            )
            decision_ulid = str(ULID())
            mesh_hash = hashlib.sha256(
                f"{tag}:{spec['key']}:mesh".encode()
            ).hexdigest()
            params_hash = hashlib.sha256(
                f"{tag}:{spec['key']}:params".encode()
            ).hexdigest()
            row = (
                await session.execute(
                    text(
                        "INSERT INTO cost_decisions "
                        "(ulid,user_id,org_id,mesh_hash,params_hash,engine_version,"
                        "filename,file_type,result_json,make_now_process,crossover_qty,"
                        "quantities,label,approval_status,approved_by_user_id,approved_at,"
                        "approval_note,stale_at,stale_reason,is_public,created_at) "
                        "VALUES "
                        "(:ulid,:user,:org,:mesh,:params,'qa-work-matrix-v1',"
                        ":filename,'step',CAST(:result AS jsonb),:process,NULL,"
                        "CAST(:quantities AS jsonb),NULL,:approval,:approver,:approved_at,"
                        ":approval_note,:stale_at,:stale_reason,false,:created_at) "
                        "RETURNING id"
                    ),
                    {
                        "ulid": decision_ulid,
                        "user": owner_id,
                        "org": org_id,
                        "mesh": mesh_hash,
                        "params": params_hash,
                        "filename": spec["filename"],
                        "result": json.dumps(result),
                        "process": spec["process"],
                        "quantities": json.dumps(result["quantities"]),
                        "approval": spec["approval_status"],
                        "approver": (
                            owner_id
                            if spec["approval_status"] == "approved"
                            else None
                        ),
                        "approved_at": spec["approved_at"],
                        "approval_note": (
                            "Approved deterministic sourcing fixture."
                            if spec["approval_status"] == "approved"
                            else None
                        ),
                        "stale_at": spec["stale_at"],
                        "stale_reason": spec["stale_reason"],
                        "created_at": spec["created_at"],
                    },
                )
            ).first()
            output["decisions"][spec["key"]] = {
                "key": spec["key"],
                "db_id": int(row[0]),
                "id": decision_ulid,
                "filename": spec["filename"],
                "approval_status": spec["approval_status"],
                "is_stale": spec["stale_at"] is not None,
                "unvalidated": not spec["validated"],
                "recommendations": spec["recommendations"],
                "process": spec["process"],
            }

        await session.commit()

    output["expected_compare"] = [
        {
            "quantity": 1,
            "a": {"process": "cnc_3axis", "unit_cost_usd": 10.0},
            "b": {"process": "mjf", "unit_cost_usd": 12.346},
            "delta_usd": 2.35,
            "delta_pct": 23.5,
        },
        {
            "quantity": 10,
            "a": {"process": "cnc_3axis", "unit_cost_usd": 20.0},
            "b": {"process": "mjf", "unit_cost_usd": 15.0},
            "delta_usd": -5.0,
            "delta_pct": -25.0,
        },
        {
            "quantity": 100,
            "a": {"process": "cnc_3axis", "unit_cost_usd": 8.0},
            "b": None,
            "delta_usd": None,
            "delta_pct": None,
        },
        {
            "quantity": 1000,
            "a": None,
            "b": {"process": "mjf", "unit_cost_usd": 7.0},
            "delta_usd": None,
            "delta_pct": None,
        },
    ]
    return output


async def snapshot(owner_id: int, rfq_title: str) -> dict[str, Any]:
    async with eng.get_session_factory()() as session:
        costs = (
            await session.execute(
                text(
                    "SELECT ulid,filename,approval_status,(stale_at <= now()) AS is_stale "
                    "FROM cost_decisions WHERE user_id=:user ORDER BY created_at,id"
                ),
                {"user": owner_id},
            )
        ).all()
        package = (
            await session.execute(
                text(
                    "SELECT ulid,title,item_count,approved_count,stale_count,"
                    "unvalidated_count,raw_cad_included,live_supplier_send,"
                    "items_json,warnings_json,metadata_json "
                    "FROM rfq_packages WHERE user_id=:user AND title=:title "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"user": owner_id, "title": rfq_title},
            )
        ).first()
        keys = (
            await session.execute(
                text(
                    "SELECT id,name,prefix,created_at,last_used_at,revoked_at,"
                    "length(hmac_index),hmac_index ~ '^[0-9a-f]{64}$',"
                    "secret_hash LIKE '$argon2id$%' "
                    "FROM api_keys WHERE user_id=:user ORDER BY id"
                ),
                {"user": owner_id},
            )
        ).all()
        audit_rows = (
            await session.execute(
                text(
                    "SELECT action,count(*) FROM audit_log "
                    "WHERE user_id=:user AND action IN "
                    "('api_key.created','api_key.revoked') "
                    "GROUP BY action ORDER BY action"
                ),
                {"user": owner_id},
            )
        ).all()
        columns = (
            await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name='api_keys' "
                    "ORDER BY ordinal_position"
                )
            )
        ).scalars().all()

    package_json = None
    if package is not None:
        package_json = {
            "id": package[0],
            "title": package[1],
            "item_count": int(package[2]),
            "approved_count": int(package[3]),
            "stale_count": int(package[4]),
            "unvalidated_count": int(package[5]),
            "raw_cad_included": bool(package[6]),
            "live_supplier_send": bool(package[7]),
            "items": package[8],
            "warnings": package[9],
            "metadata": package[10],
        }
    return {
        "cost_decisions": [
            {
                "id": row[0],
                "filename": row[1],
                "approval_status": row[2],
                "is_stale": bool(row[3]),
            }
            for row in costs
        ],
        "rfq_package": package_json,
        "api_keys": [
            {
                "id": int(row[0]),
                "name": row[1],
                "prefix": row[2],
                "created_at": str(row[3]),
                "last_used_at": str(row[4]) if row[4] else None,
                "revoked_at": str(row[5]) if row[5] else None,
                "hmac_length": int(row[6]),
                "hmac_hex": bool(row[7]),
                "argon2id": bool(row[8]),
            }
            for row in keys
        ],
        "api_key_audit": {row[0]: int(row[1]) for row in audit_rows},
        "api_key_columns": list(columns),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    seed_parser = subparsers.add_parser("seed")
    seed_parser.add_argument("tag")
    seed_parser.add_argument("password")
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("owner_id", type=int)
    snapshot_parser.add_argument("rfq_title")
    args = parser.parse_args()
    try:
        if args.action == "seed":
            result = await seed(args.tag, args.password)
        else:
            result = await snapshot(args.owner_id, args.rfq_title)
        print(json.dumps(result, default=str))
    finally:
        await eng.dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
