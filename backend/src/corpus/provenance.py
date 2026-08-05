"""Shared fail-closed provenance validation for redistributable corpus assets."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


# Deliberately small reviewed set. GitHub's license API returns these canonical
# SPDX identifiers directly. New identifiers require a code review instead of
# silently accepting any string that merely looks license-like.
_APPROVED_SPDX_IDS = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSL-1.0",
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
        "CC0-1.0",
        "CERN-OHL-P-2.0",
        "CERN-OHL-S-2.0",
        "CERN-OHL-W-2.0",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "MIT",
        "MPL-2.0",
        "Unlicense",
    }
)

# SPDX permits locally defined LicenseRef identifiers. CadVerify accepts one
# only when the identifier explicitly records that a human license review was
# retained outside the corpus. The suffix is an operator-owned review/evidence
# identifier, not free-form prose.
_REVIEWED_LICENSE_REF = re.compile(
    r"\ALicenseRef-CadVerify-Reviewed-[A-Za-z0-9][A-Za-z0-9._-]{2,79}\Z"
)


def has_documented_license(value: str) -> bool:
    """Accept only a reviewed SPDX id or explicit reviewed LicenseRef."""
    normalized = value.strip()
    return normalized in _APPROVED_SPDX_IDS or bool(
        _REVIEWED_LICENSE_REF.fullmatch(normalized)
    )


def has_valid_source_url(value: str) -> bool:
    """Require a credential-free HTTPS provenance URL with a real host."""
    candidate = value.strip()
    if not candidate or any(ch.isspace() for ch in candidate):
        return False
    try:
        parsed = urlsplit(candidate)
        # Reading .port validates malformed/out-of-range ports as well.
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def has_complete_provenance(source_url: str, license_name: str) -> bool:
    """Return true only when both independently fail-closed checks pass."""
    return has_valid_source_url(source_url) and has_documented_license(license_name)
