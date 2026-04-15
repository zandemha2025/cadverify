"""Cloudflare Turnstile server-side verification.

Called BEFORE OAuth redirect or magic-link send. Fails closed on any non-
success response (network error, non-200, success=false).
"""
from __future__ import annotations

import os

import httpx
from fastapi import HTTPException

SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def _fail() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "captcha_failed",
            "message": "Captcha verification failed.",
            "doc_url": "https://docs.cadverify.com/errors#captcha_failed",
        },
    )


async def verify_turnstile(token: str, remoteip: str | None) -> None:
    """Raise HTTPException(400, {code: captcha_failed}) on any failure."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                SITEVERIFY,
                data={
                    "secret": os.environ["TURNSTILE_SECRET"],
                    "response": token,
                    **({"remoteip": remoteip} if remoteip else {}),
                },
            )
    except Exception:
        raise _fail()
    if r.status_code != 200:
        raise _fail()
    try:
        body = r.json()
    except Exception:
        raise _fail()
    if body.get("success") is not True:
        raise _fail()
