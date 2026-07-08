"""Persisted per-org calibration bundle (W5) — mirrors the shop_profile store.

The ground-truth loop (``src/costing/groundtruth.py``) fits a ``Calibration`` +
a ``ResidualModel`` in memory from ``tune()`` / ``run_loop()``. This module gives
that result a DURABLE, ORG-NAMESPACED home on local disk — exactly the way
``shop_profile.py`` persists a ``ShopProfile`` — so the served cost API can LOAD
a shop's tuned calibration at request time instead of re-running the loop on
every request.

CAD-as-IP: the store is a local JSON directory; nothing here opens a socket.

A ``CalibrationBundle`` carries BOTH halves the live CI path needs:

  * the tuned ``Calibration`` (per-process correction factors, provenance
    TUNED) — item 2 of W5 ("persist the tuned Calibration"), and
  * the held-out ``Residual`` rows the ``ResidualModel`` is rebuilt from, so the
    MEASURED empirical bands survive a process restart.

Honesty rail preserved end-to-end: each persisted residual keeps its
``stand_in`` flag, so a rebuilt ``ResidualModel`` reports ``from_real`` exactly
as the in-memory one did. A stand-in residual can shape the spread but can never
present ``validated=True`` — the persistence layer cannot launder it.

Store location resolves (in order): explicit ``store_dir`` arg >
``CADVERIFY_CALIBRATION_DIR`` env > ``backend/data/calibrations``. The env hook
lets a test point the served path at a scratch dir without touching the shared
data tree.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.costing.groundtruth import Calibration, Residual, ResidualModel

SCHEMA_VERSION = 1

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DEFAULT_DIR = os.path.normpath(
    os.path.join(_THIS_DIR, "..", "..", "data", "calibrations")
)


def default_store_dir() -> str:
    """Resolve the calibration store dir at CALL time (env-overridable)."""
    return os.environ.get("CADVERIFY_CALIBRATION_DIR") or _STATIC_DEFAULT_DIR


def _slug(org_id: str) -> str:
    """ULID org ids are already filesystem-safe; sanitize defensively anyway."""
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", (org_id or "").strip()).strip("-")
    return s or "org"


def bundle_path(org_id: str, store_dir: Optional[str] = None) -> str:
    return os.path.join(store_dir or default_store_dir(), f"{_slug(org_id)}.json")


@dataclass
class CalibrationBundle:
    """The durable, org-scoped output of one recalibration."""

    org_id: str
    calibration: Calibration
    residuals: list                       # list[Residual] — held-out, drives the CI
    from_real: bool
    n_records: int = 0
    n_real: int = 0
    n_standin: int = 0
    heldout_metrics_real: Optional[dict] = None
    claim: str = ""
    fitted_on: str = ""
    created: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: int = SCHEMA_VERSION

    def residual_model(self) -> ResidualModel:
        """Rebuild the live CI source from the persisted held-out residuals."""
        return ResidualModel(self.residuals)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "org_id": self.org_id,
            "calibration": self.calibration.to_dict(),
            "residuals": [asdict(r) for r in self.residuals],
            "from_real": self.from_real,
            "n_records": self.n_records,
            "n_real": self.n_real,
            "n_standin": self.n_standin,
            "heldout_metrics_real": self.heldout_metrics_real,
            "claim": self.claim,
            "fitted_on": self.fitted_on,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationBundle":
        cal_fields = Calibration.__dataclass_fields__  # type: ignore[attr-defined]
        cal = Calibration(
            **{k: v for k, v in (d.get("calibration") or {}).items()
               if k in cal_fields}
        )
        res_fields = Residual.__dataclass_fields__  # type: ignore[attr-defined]
        residuals = [
            Residual(**{k: v for k, v in rd.items() if k in res_fields})
            for rd in (d.get("residuals") or [])
        ]
        return cls(
            org_id=d["org_id"],
            calibration=cal,
            residuals=residuals,
            from_real=bool(d.get("from_real", False)),
            n_records=int(d.get("n_records", 0)),
            n_real=int(d.get("n_real", 0)),
            n_standin=int(d.get("n_standin", 0)),
            heldout_metrics_real=d.get("heldout_metrics_real"),
            claim=d.get("claim", ""),
            fitted_on=d.get("fitted_on", ""),
            created=d.get("created", ""),
            schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
        )


def save_bundle(bundle: CalibrationBundle, store_dir: Optional[str] = None) -> str:
    """Persist a bundle (atomic-ish). Returns the written path."""
    store_dir = store_dir or default_store_dir()
    os.makedirs(store_dir, exist_ok=True)
    path = bundle_path(bundle.org_id, store_dir)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(bundle.to_dict(), f, indent=2, sort_keys=False)
    os.replace(tmp, path)
    return path


def load_bundle(org_id: str, store_dir: Optional[str] = None) -> Optional[CalibrationBundle]:
    """Load an org's bundle, or None if it has never been calibrated."""
    path = bundle_path(org_id, store_dir)
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return CalibrationBundle.from_dict(json.load(f))


def delete_bundle(org_id: str, store_dir: Optional[str] = None) -> bool:
    path = bundle_path(org_id, store_dir)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
