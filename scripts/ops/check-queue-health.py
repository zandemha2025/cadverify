#!/usr/bin/env python3
"""Fetch the admin queue-health proof endpoint.

Environment:
  CADVERIFY_API_URL  Base API URL, default http://127.0.0.1:8000
  CADVERIFY_API_KEY  Admin API key or dashboard proxy token accepted by the API
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    base = os.getenv("CADVERIFY_API_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.getenv("CADVERIFY_API_KEY")
    if not token:
        print("CADVERIFY_API_KEY is required", file=sys.stderr)
        return 2

    req = urllib.request.Request(
        f"{base}/api/v1/admin/ops/queue-health",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"queue-health returned HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
        return 1

    print(json.dumps(body, indent=2, sort_keys=True))
    active = (
        int(body.get("jobs", {}).get("active_count", 0))
        + int(body.get("batches", {}).get("active_count", 0))
        + int(body.get("batch_items", {}).get("active_count", 0))
    )
    stale = int(body.get("batches", {}).get("stale_heartbeat_count", 0))
    due = int(body.get("webhooks", {}).get("retry_due_count", 0))
    return 1 if stale or due else 0 if active >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
