"""Redis key builders for cluster-safe, PII-free magic-link state."""

from __future__ import annotations

import hashlib


def _email_slot(email_normalized: str) -> str:
    # Redis Cluster hashes only the text inside {...}. A one-way email digest
    # keeps token, active pointer, and resend window in one slot without putting
    # the address itself in Redis key names or operational key listings.
    return hashlib.sha256(email_normalized.encode()).hexdigest()


def magic_active_key(email_normalized: str) -> str:
    return f"magic:{{{_email_slot(email_normalized)}}}:active"


def magic_token_key(email_normalized: str, token: str) -> str:
    token_digest = hashlib.sha256(token.encode()).hexdigest()
    return f"magic:{{{_email_slot(email_normalized)}}}:token:{token_digest}"


def magic_send_key(email_normalized: str) -> str:
    return f"magic:{{{_email_slot(email_normalized)}}}:send"


def magic_generation_key(email_normalized: str) -> str:
    return f"magic:{{{_email_slot(email_normalized)}}}:generation"
