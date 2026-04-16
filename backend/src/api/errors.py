"""Structured error responses with stable error codes."""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

# Stable error codes — do not rename or remove once published
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
    503: "SERVICE_UNAVAILABLE",
    504: "ANALYSIS_TIMEOUT",
}

DOC_BASE = "https://docs.cadverify.com/errors"


def _build_error(status_code: int, code: str, message: str) -> dict:
    return {
        "code": code,
        "message": message,
        "doc_url": f"{DOC_BASE}/{code}",
    }


async def structured_http_error_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    code = ERROR_CODES.get(exc.status_code, "UNKNOWN_ERROR")
    # If detail is already a dict with 'code', use it as-is
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code, content=exc.detail
        )
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_error(exc.status_code, code, message),
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
