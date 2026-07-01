"""Per-shop calibration profiles — bind every cost DEFAULT to ONE shop's reality.

This is the answer to error-bucket #1 (generic default rates, the single largest
*removable* contributor to absolute-cost error, measured at ±44–47% in
`outputs/error-decomposition.md`). A `ShopProfile` captures a real shop's own
numbers — loaded labor rate, per-process machine $/hr, negotiated material lot
prices, utilization, overhead, target margin, and region — and feeds them into
the cost model as SHOP-provenance bindings. Every line item then shows whether it
came from THIS shop's profile (SHOP) or a generic fallback (DEFAULT).

CAD-as-IP: profiles persist to a LOCAL JSON store. Nothing here opens a socket.

How a profile binds to the engine
---------------------------------
`ShopProfile.to_shop_overrides()` emits the same dotted-key form the rate card
already understands (see `rates._apply_override`), e.g.::

    labor_rate                 -> global labor $/hr
    margin / overhead / utilization
    machine_rate.SLS           -> per-process machine $/hr
    material_price.PA12 (Nylon 12)  / material_price.@polymer
    region_labor.MX / region_material.MX / region_tooling.MX

`build_rate_card(..., shop_overrides=..., shop_name=..., shop_region=...)` applies
these as SHOP, then any ad-hoc `rate_overrides` as USER on top (USER wins).

Region & double-counting (honest note)
--------------------------------------
The engine models effective labor as `labor_rate × region_labor[region]`. A
calibrated shop's `labor_rate` is its TRUE loaded rate, which already encodes its
region — so a fully-bound profile should pin its `region_multipliers` (typically
labor=1.0) to avoid charging a regional factor twice. The example profiles do
exactly this; it is documented in outputs/calibration-readme.md.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

SCHEMA_VERSION = 1

# Local profile store (CAD-as-IP: never leaves the box). Resolves to
# backend/data/shop_profiles/ regardless of cwd.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STORE_DIR = os.path.normpath(
    os.path.join(_THIS_DIR, "..", "..", "data", "shop_profiles"))


@dataclass
class ShopProfile:
    """One shop's real cost reality. Every field is optional except `name`;
    anything left None/empty falls back to the generic DEFAULT rate card and is
    clearly tagged DEFAULT in the output (so the gaps in a half-calibrated shop
    are visible, not hidden).
    """

    name: str
    region: str = "US"

    # ---- global levers (None => keep generic DEFAULT) -------------------
    labor_rate: Optional[float] = None        # $/hr loaded shop-floor labor
    margin: Optional[float] = None            # target margin fraction (price vs should-cost)
    overhead: Optional[float] = None          # indirect-cost markup on conversion (machine+labor+setup)
    utilization: Optional[float] = None        # machine utilization 0<u<=1 (idle-recovery on machine cost)
    stock_allowance: Optional[float] = None    # CNC billet oversize factor

    # ---- per-process machine $/hr (keys are ProcessType NAMES) ----------
    #   e.g. {"CNC_3AXIS": 95, "SLS": 28, "INJECTION_MOLDING": 60}
    machine_rates: dict = field(default_factory=dict)

    # ---- material lot prices $/kg (exact material name OR "@<class>") ----
    #   e.g. {"PA12 (Nylon 12)": 7.5, "@aluminum": 9.0}
    material_prices: dict = field(default_factory=dict)

    # ---- explicit regional multipliers for THIS shop's region -----------
    #   {"labor": 1.0, "material": 1.0, "tooling": 1.0}; pin labor=1.0 when
    #   labor_rate is the shop's absolute loaded rate (avoids double-count).
    region_multipliers: dict = field(default_factory=dict)

    # ---- metadata / provenance of the numbers ---------------------------
    source: str = ""          # how these rates were obtained (audit trail)
    notes: str = ""
    created: str = field(default_factory=lambda: date.today().isoformat())
    schema_version: int = SCHEMA_VERSION

    # ── binding ──────────────────────────────────────────────────────────
    def to_shop_overrides(self) -> dict:
        """Flatten the profile into the rate card's dotted-key override form.

        Only keys the shop actually set are emitted — a missing key stays a
        generic DEFAULT (and reads DEFAULT in the output), which is the honest
        behavior for a partially-calibrated shop.
        """
        out: dict = {}
        for gkey in ("labor_rate", "margin", "overhead", "utilization",
                     "stock_allowance"):
            v = getattr(self, gkey)
            if v is not None:
                out[gkey] = float(v)
        for proc_name, rate in (self.machine_rates or {}).items():
            out[f"machine_rate.{proc_name}"] = float(rate)
        for mat_name, price in (self.material_prices or {}).items():
            out[f"material_price.{mat_name}"] = float(price)
        rm = self.region_multipliers or {}
        for vec in ("labor", "material", "tooling"):
            if vec in rm:
                out[f"region_{vec}.{self.region}"] = float(rm[vec])
        return out

    # ── serialization ────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ShopProfile":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in d.items() if k in known}
        if "name" not in clean:
            raise ValueError("shop profile is missing required field 'name'")
        return cls(**clean)


# ──────────────────────────────────────────────────────────────────────────
# Local persistence (no network; CAD-as-IP)
# ──────────────────────────────────────────────────────────────────────────
def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "shop"


def profile_path(name: str, store_dir: Optional[str] = None) -> str:
    return os.path.join(store_dir or DEFAULT_STORE_DIR, f"{_slug(name)}.json")


def save_profile(profile: ShopProfile, store_dir: Optional[str] = None) -> str:
    """Persist a profile to the local store. Returns the written path."""
    store_dir = store_dir or DEFAULT_STORE_DIR
    os.makedirs(store_dir, exist_ok=True)
    path = profile_path(profile.name, store_dir)
    with open(path, "w") as f:
        json.dump(profile.to_dict(), f, indent=2, sort_keys=False)
    return path


def load_profile(name_or_path: str, store_dir: Optional[str] = None) -> ShopProfile:
    """Load a profile by name (from the store) or by an explicit JSON path."""
    if name_or_path.endswith(".json") and os.path.isfile(name_or_path):
        path = name_or_path
    else:
        path = profile_path(name_or_path, store_dir)
        if not os.path.isfile(path) and os.path.isfile(name_or_path):
            path = name_or_path
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"No shop profile {name_or_path!r} (looked in {path}). "
            f"Available: {', '.join(list_profiles(store_dir)) or '(none)'}")
    with open(path) as f:
        return ShopProfile.from_dict(json.load(f))


def list_profiles(store_dir: Optional[str] = None) -> list:
    store_dir = store_dir or DEFAULT_STORE_DIR
    if not os.path.isdir(store_dir):
        return []
    return sorted(f[:-5] for f in os.listdir(store_dir) if f.endswith(".json"))


def resolve_shop(shop, store_dir: Optional[str] = None) -> Optional[ShopProfile]:
    """Coerce a ShopProfile | name | path | None into a ShopProfile | None."""
    if shop is None:
        return None
    if isinstance(shop, ShopProfile):
        return shop
    if isinstance(shop, dict):
        return ShopProfile.from_dict(shop)
    if isinstance(shop, str):
        return load_profile(shop, store_dir)
    raise TypeError(f"cannot resolve shop profile from {type(shop).__name__}")
