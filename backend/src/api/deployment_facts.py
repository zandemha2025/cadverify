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

Never returned: bucket names, endpoint URLs or hostnames, account ids, ARNs,
keys or any other credential. The store's own settings are reduced to a kind,
a region code and an encryption flag; an operator's declared text is limited to
plain words and refused outright if it looks like a URL, a hostname or IP
address, an ARN, an account id, an email address or a key, or if it repeats
one of the store's own settings (bucket, prefix, endpoint host, key id).
"""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, Response

router = APIRouter(tags=["deployment"])

# Plain words only: letters, digits, spaces and light punctuation (no ":", "/",
# "@" or "=" so no URL, ARN, email or key=value can be formed).
_TEXT = re.compile(r"[^\w .,;()&'’-]")
# Shapes that must never be published even after the character filter.
_SECRET_LIKE = re.compile(
    r"https?|s3\b|\barn\b|amazonaws|\.com\b|\.net\b|\.io\b|bucket"  # locations
    r"|\d{10,}"  # account ids and other long numbers
    r"|[A-Za-z0-9_\-]{24,}"  # tokens and keys
    # Hostnames and domains (fly.dev, minio.internal): a dot between a name and a
    # label of two or more characters. "U.S." and "v1.2" stay plain words.
    r"|[A-Za-z0-9\-]\.[A-Za-z][A-Za-z0-9\-]"
    r"|\b\d{1,3}(?:\.\d{1,3}){3}\b"  # IPv4 addresses
    r"|\blocalhost\b",
    re.IGNORECASE,
)

# The store's own settings: none of them is ever published, even when an operator
# writes one into a declared fact by mistake and it reads as plain words.
_STORE_SETTINGS = (
    "OBJECT_STORE_S3_BUCKET",
    "OBJECT_STORE_S3_PREFIX",
    "OBJECT_STORE_S3_KMS_KEY_ID",
    "DIRECT_UPLOAD_S3_BUCKET",
    "DIRECT_UPLOAD_S3_PREFIX",
)
_STORE_ENDPOINTS = ("OBJECT_STORE_S3_ENDPOINT", "DIRECT_UPLOAD_S3_ENDPOINT")


def _store_values() -> list[str]:
    """The configured bucket names, prefixes, key id and endpoint hosts (and each
    endpoint's first label, e.g. a bucket or account in a virtual-host name)."""
    from urllib.parse import urlsplit

    values = [os.getenv(name, "").strip().strip("/") for name in _STORE_SETTINGS]
    for name in _STORE_ENDPOINTS:
        raw = os.getenv(name, "").strip()
        try:
            host = urlsplit(raw if "://" in raw else f"//{raw}").hostname or ""
        except ValueError:
            host = ""
        values += [host, host.split(".", 1)[0]]
    return [v.lower() for v in values if len(v) >= 4]


def _repeats_store_setting(text: str) -> bool:
    low = text.lower()
    return any(value in low for value in _store_values())


def _declared_text(name: str) -> str | None:
    raw = os.getenv(name, "").strip()
    if not raw or _SECRET_LIKE.search(raw) or _repeats_store_setting(raw):
        return None
    clean = " ".join(_TEXT.sub("", raw).split())[:200].strip()
    if not clean or _SECRET_LIKE.search(clean) or _repeats_store_setting(clean):
        return None
    return clean


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
