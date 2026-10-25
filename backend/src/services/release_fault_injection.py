"""Fail-closed fault selection for real release-evidence browser runs.

The hooks in this module are inert unless ``E2E_FAULT_INJECTION_TOKEN`` is set
on the API process and the caller supplies the same secret.  A selected mode is
then persisted on one accepted design job or batch; workers never consult a
global switch.  This keeps release testing deterministic without making shared
infrastructure unavailable or allowing one run to affect unrelated work.
"""
from __future__ import annotations

import hmac
import os
from typing import AbstractSet

from fastapi import HTTPException, Request

FAULT_TOKEN_HEADER = "x-proofshape-e2e-token"
FAULT_MODE_HEADER = "x-proofshape-e2e-fault"

DESIGN_FAULT_MODES = frozenset({"design_queue", "cad_kernel", "object_store"})
BATCH_FAULT_MODES = frozenset({"batch_queue", "batch_delay"})


def requested_release_fault(
    request: Request,
    allowed: AbstractSet[str],
) -> str | None:
    """Return an authorized record-scoped fault mode, otherwise ``None``.

    Missing configuration, a missing token, and a wrong token all behave like
    fault injection does not exist.  Only an already-authorized caller receives
    a 400 for a misspelled or out-of-scope mode.
    """

    configured = os.getenv("E2E_FAULT_INJECTION_TOKEN", "").strip()
    supplied = request.headers.get(FAULT_TOKEN_HEADER, "")
    if not configured or not supplied or not hmac.compare_digest(configured, supplied):
        return None

    mode = request.headers.get(FAULT_MODE_HEADER, "").strip()
    if not mode:
        return None
    if mode not in allowed:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_RELEASE_FAULT",
                "message": "The requested release-evidence fault mode is not allowed for this operation.",
            },
        )
    return mode
