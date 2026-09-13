"""Structured error responses with stable error codes."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from src.config.public_urls import error_doc_url

# Stable error codes — do not rename or remove once published
# Failed CAD uploads need a useful WHY without reflecting untrusted file bytes.
# This classifier consumes only server-authored error strings from the parse seam.
def cad_upload_diagnosis(message: str) -> dict[str, Any] | None:
    """Return a stable, honest diagnosis for known CAD-ingest failures.

    Unknown 400s are deliberately left alone: inventing a geometry diagnosis is
    worse than a generic BAD_REQUEST. ``repairable`` means ProofShape can safely
    repair the uploaded bytes without changing design intent today.
    """
    value = (message or "").strip()
    lower = value.lower()

    if "empty file uploaded" in lower:
        return {
            "failure_class": "empty_file",
            "plain_reason": "The upload contains no file data.",
            "location": None,
            "repairable": False,
            "next_action": "Export the part again and upload the new file.",
        }
    if "unsupported file type" in lower:
        return {
            "failure_class": "unsupported_type",
            "plain_reason": "The file is not one of the CAD exchange formats ProofShape can read.",
            "location": None,
            "repairable": False,
            "next_action": "Export the original part as STL, STEP, STP, IGES, or IGS.",
        }
    if (
        "does not appear to be a valid" in lower
        or "too small to be a valid stl" in lower
        or "could not read step geometry" in lower
        or "could not read iges geometry" in lower
        or "not a valid/supported" in lower
    ):
        return {
            "failure_class": "invalid_or_incomplete_export",
            "plain_reason": "The file name uses a supported format, but the saved CAD data is incomplete or invalid.",
            "location": None,
            "repairable": False,
            "next_action": "Re-export the original model as a clean STL, STEP, STP, IGES, or IGS file.",
        }
    if "triangles, exceeds" in lower or "reduce mesh resolution" in lower:
        return {
            "failure_class": "mesh_too_dense",
            "plain_reason": "The mesh contains more triangles than this verification path can safely process.",
            "location": None,
            "repairable": False,
            "next_action": "Reduce mesh resolution without changing the part dimensions, then upload it again.",
        }
    if any(token in lower for token in ("tessell", "triangulat", "mesher", "unsupported surface", "failed to parse mesh")):
        return {
            "failure_class": "tessellation_failed",
            "plain_reason": "The CAD surfaces could not be converted into a complete verification mesh.",
            "location": None,
            "repairable": False,
            "next_action": "Heal the solid in CAD or export a clean STEP or STL, then upload it again.",
        }
    return None


ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "FILE_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    501: "NOT_IMPLEMENTED",
    503: "SERVICE_UNAVAILABLE",
    504: "ANALYSIS_TIMEOUT",
}

def _build_error(
    status_code: int,
    code: str,
    message: str,
    *,
    detail: Any | None = None,
) -> dict:
    payload = {
        "code": code,
        "message": message,
        "doc_url": error_doc_url(code),
    }
    if detail is not None:
        payload["detail"] = detail
    return payload


async def structured_http_error_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    code = ERROR_CODES.get(exc.status_code, "UNKNOWN_ERROR")
    # If detail is already a dict with 'code', use it as-is
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code, content=exc.detail, headers=exc.headers
        )
    if isinstance(exc.detail, dict):
        message = str(exc.detail.get("message") or exc.detail.get("reason") or exc.detail)
        detail = exc.detail
    else:
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        detail = None
    payload = _build_error(exc.status_code, code, message, detail=detail)
    if exc.status_code == 400 and isinstance(message, str):
        diagnosis = cad_upload_diagnosis(message)
        if diagnosis is not None:
            payload["diagnosis"] = diagnosis
    return JSONResponse(
        status_code=exc.status_code,
        content=payload,
        headers=exc.headers,
    )


async def structured_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_build_error(
            422,
            "VALIDATION_ERROR",
            str(exc.errors()),
        ),
    )
