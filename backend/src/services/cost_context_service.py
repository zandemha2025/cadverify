"""Shared dynamic context binding for live and batch cost decisions.

The costing engine is pure, but the effective options are not: an organization
may publish shop/rate/material libraries, declare owned machines and a part
service environment, and serve a measured calibration.  Both entry points must
hydrate those inputs identically before calling ``estimate_decision``.
"""
from __future__ import annotations

import copy
import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.costing.estimate import EstimateOptions

logger = logging.getLogger("cadverify.cost_context_service")


def available_shops() -> list[dict]:
    """Return the local, allow-listed shop profiles exposed by the cost API."""
    from src.costing import list_profiles
    from src.costing.shop_profile import load_profile

    out: list[dict] = []
    for slug in list_profiles():
        try:
            profile = load_profile(slug)
        except Exception:
            logger.warning("shop profile %r failed to load; skipping", slug)
            continue
        out.append(
            {
                "id": slug,
                "name": profile.name,
                "region": profile.region,
                "source": profile.source or None,
            }
        )
    return out


def resolve_local_shop(shop: Optional[str]) -> Optional[str]:
    """Resolve a local shop name/slug without accepting arbitrary file paths."""
    if not shop or not shop.strip():
        return None

    from src.costing.shop_profile import _slug

    requested = shop.strip()
    requested_slug = _slug(requested)
    shops = available_shops()
    for candidate in shops:
        if (
            requested == candidate["id"]
            or requested_slug == candidate["id"]
            or requested.lower() == candidate["name"].lower()
        ):
            return candidate["id"]
    raise HTTPException(
        status_code=400,
        detail=(
            f"Unknown shop {requested!r}. Available: "
            f"{[candidate['id'] for candidate in shops] or '(none)'}"
        ),
    )


async def resolve_governed_shop(
    session: AsyncSession | None,
    org_id: str | None,
    shop: Optional[str],
):
    """Return an effective governed shop binding for exactly ``org_id``."""
    raw = (shop or "").strip()
    if not raw or session is None or not isinstance(org_id, str) or not org_id:
        return None

    from src.services.shop_library_service import (
        governed_shop_profile,
        resolve_shop_overrides_for,
        shop_library_enabled,
    )

    if not shop_library_enabled():
        return None

    from src.costing.shop_profile import _slug

    slug = _slug(raw)
    payload = await resolve_shop_overrides_for(session, org_id, slug)
    if payload is None:
        return None
    return governed_shop_profile(slug, payload)


async def resolve_cost_shop(
    session: AsyncSession | None,
    org_id: str | None,
    shop: Optional[str],
) -> tuple[Optional[str], object]:
    """Resolve governed-first, then local, returning canonical slug + binding."""
    governed = await resolve_governed_shop(session, org_id, shop)
    if governed is not None:
        return governed.slug, governed
    slug = resolve_local_shop(shop)
    return slug, slug


async def bind_cost_org_context(
    session: AsyncSession | None,
    org_id: str | None,
    mesh_hash: str,
    options: EstimateOptions,
    *,
    service_environment_supplied: bool = False,
    request_service_environment: dict | None = None,
    include_analogy: bool = False,
) -> list | None:
    """Hydrate every organization-scoped input used by a cost decision.

    ``options`` is deliberately mutated once, before it crosses the executor
    boundary.  The return value is the optional analogy feed used only by the
    live response's ensemble calculation.  An explicit request environment is
    applied last so it cannot lose to mutable stored part context.
    """
    analogy_records = None
    bound_org_id = org_id if isinstance(org_id, str) and org_id else None

    if session is not None and bound_org_id is not None:
        # Machine declarations are a graceful-degrade lens.  Preserve the live
        # route's existing behavior: a failure here must not fail costing.
        try:
            from src.services.machine_inventory_service import (
                load_org_inventory,
                load_shop_caps,
            )

            inventory = await load_org_inventory(session, bound_org_id)
            if inventory:
                options.inventory = tuple(inventory)
                options.shop_caps = await load_shop_caps(session, bound_org_id)
        except Exception:
            logger.warning(
                "machine-inventory feed failed for org %s; decision proceeds "
                "without the machine lens",
                bound_org_id,
                exc_info=True,
            )

        # Service environment is a safety gate, not an optional ranking lens.
        # Keep it independent from inventory hydration and fail closed when its
        # authoritative stored state cannot be read.  An explicit request value
        # (including {}) is already authoritative and needs no database lookup.
        if not service_environment_supplied:
            from src.services.part_context_service import get_context

            try:
                context = await get_context(session, bound_org_id, mesh_hash)
            except Exception as exc:
                logger.error(
                    "service-environment feed failed for org %s",
                    bound_org_id,
                    exc_info=True,
                )
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Stored service environment is temporarily unavailable; "
                        "cost decision was not computed."
                    ),
                ) from exc
            stored_environment = (
                getattr(context, "service_environment", None)
                if context is not None
                else None
            )
            if stored_environment:
                options.service_environment = stored_environment

        from src.services.groundtruth_service import load_served_calibration

        residual_model, calibration = load_served_calibration(bound_org_id)
        if residual_model is not None:
            options.residual_model = residual_model
        if calibration is not None:
            options.calibration = calibration

        from src.services.rate_library_service import resolve_rate_table_for_org

        base_table = await resolve_rate_table_for_org(session, bound_org_id)
        if base_table is not None:
            options.base_rate_table = base_table

        from src.costing.rates import RATE_CARD_V0
        from src.services.material_library_service import (
            resolve_material_overrides_for,
        )

        material_payload = await resolve_material_overrides_for(
            session, bound_org_id
        )
        material_prices = (material_payload or {}).get("material_prices") or {}
        material_definitions = (material_payload or {}).get("materials") or {}
        if material_prices or material_definitions:
            # Published-library caches return shared payload objects.  Never
            # mutate one while applying this request's material overlay.
            base = copy.deepcopy(
                options.base_rate_table
                if options.base_rate_table is not None
                else RATE_CARD_V0
            )
            if material_prices:
                merged_prices = dict(base.get("material_prices") or {})
                merged_prices.update(material_prices)
                base["material_prices"] = merged_prices
            if material_definitions:
                merged_definitions = dict(base.get("materials") or {})
                merged_definitions.update(material_definitions)
                base["materials"] = merged_definitions
            options.base_rate_table = base

        if include_analogy:
            from src.services.groundtruth_service import load_org_ground_truth

            analogy_records = await load_org_ground_truth(session, bound_org_id)

    # Request-local context is authoritative even when it is explicitly empty.
    if service_environment_supplied:
        options.service_environment = request_service_environment

    return analogy_records
