"""What this deployment can say about where data lives, from its configuration.

GET /api/v1/deployment (public, no sign-in) feeds the public Security, Privacy
and Data processing pages and the in-app Files and data page, so they state
only what the running configuration makes true:

- ``file_storage``: read from the object-store settings the code itself uses
  (OBJECT_STORE_BACKEND, OBJECT_STORE_S3_REGION, OBJECT_STORE_S3_ENDPOINT,
  OBJECT_STORE_S3_KMS_KEY_ID). With a KMS key set, every stored file is
  written with SSE-KMS (src/storage/s3.py), so that is a code fact.
- ``declared``: facts the code can't see (hosting provider and region, encryption
  at rest of the database and disks, backup retention). They come only from
  operator-set variables (DEPLOYMENT_HOSTING, DEPLOYMENT_DATA_REGION,
  DEPLOYMENT_ENCRYPTION_AT_REST, DEPLOYMENT_BACKUP_RETENTION_DAYS); when unset
  the answer is null and the pages say it isn't stated, never a guess.

No bucket names, hostnames, keys or endpoints are returned.
"""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, Response

router = APIRouter(tags=["deployment"])

_TEXT = re.compile(r"[^\w .,;:()/+&'’-]")


def _declared_text(name: str) -> str | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    clean = _TEXT.sub("", raw)[:200].strip()
    return clean or None


def _declared_days(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw.isdigit():
        return None
    days = int(raw)
    return days if 0 < days <= 3650 else None


def file_storage() -> dict:
    backend = os.getenv("OBJECT_STORE_BACKEND", "local").strip().lower() or "local"
    if backend != "s3":
        return {"kind": "local", "region": None, "encryption": None, "s3_compatible": False}
    custom = bool(os.getenv("OBJECT_STORE_S3_ENDPOINT", "").strip())
    region = os.getenv("OBJECT_STORE_S3_REGION", "").strip()
    region = region if re.fullmatch(r"[a-z]{2}(-[a-z]+)+-\d", region) else None
    kms = bool(os.getenv("OBJECT_STORE_S3_KMS_KEY_ID", "").strip())
    return {
        "kind": "s3",
        "region": region,
        # Set by the code on every write when a KMS key is configured.
        "encryption": "sse-kms" if kms else None,
        "s3_compatible": custom,
    }


def deployment_facts() -> dict:
    return {
        "file_storage": file_storage(),
        "declared": {
            "hosting": _declared_text("DEPLOYMENT_HOSTING"),
            "data_region": _declared_text("DEPLOYMENT_DATA_REGION"),
            "encryption_at_rest": _declared_text("DEPLOYMENT_ENCRYPTION_AT_REST"),
            "backup_retention_days": _declared_days("DEPLOYMENT_BACKUP_RETENTION_DAYS"),
        },
    }


@router.get("/deployment")
async def get_deployment_facts(response: Response) -> dict:
    response.headers["Cache-Control"] = "public, max-age=300"
    return deployment_facts()
