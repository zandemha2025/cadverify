"""The organization that owns this deployment's single sign-on identity provider.

A deployment has one SAML IdP (``saml/settings.json``) and at most one OIDC
issuer (``OIDC_ISSUER``). ``SSO_ORG_ID`` names the organization those identity
providers belong to. It is the only org whose IdP group mappings apply at sign-in
and the only org a mapping can be created in, and SAML may attach a sign-in to
an existing same-email account only when that account is already bound to the
same IdP identity, is a member of this org, or was created by SAML before
identities were bound.

In a release whose AUTH_MODE uses SSO (saml, hybrid, or oidc with group mapping
on) an unset ``SSO_ORG_ID`` refuses to start, because the alternative is a
silent loss of group-based access. ``SSO_ORG_ID=none`` states explicitly that no
org owns the IdP yet (a first install, before its organization exists): it
starts, and no mapping applies. Outside a release an unset value logs a warning
and no mapping applies.
"""
from __future__ import annotations

import logging
import os

from src.config.production import is_production

logger = logging.getLogger("cadverify.sso_org")

SSO_ORG_ENV = "SSO_ORG_ID"
# The explicit "no owning org yet" value.
SSO_ORG_NONE = "none"


def _raw_sso_org() -> str:
    return (os.getenv(SSO_ORG_ENV) or "").strip()


def sso_org_id() -> str | None:
    """The org that owns this deployment's IdP, or None when there is none."""
    value = _raw_sso_org()
    if not value or value.lower() == SSO_ORG_NONE:
        return None
    return value


def _oidc_group_mapping_enabled() -> bool:
    raw = os.getenv("OIDC_GROUPS_CLAIM")
    return raw is None or bool(raw.strip())


def sso_org_required() -> bool:
    """Whether this deployment's AUTH_MODE needs an IdP-owning org.

    SAML (``saml``/``hybrid``) always does: group mappings and account linking
    both depend on it. ``oidc`` does unless group mapping is switched off with
    an explicitly blank ``OIDC_GROUPS_CLAIM`` (OIDC linking is already bound to
    issuer + subject).
    """
    mode = (os.getenv("AUTH_MODE") or "google").strip().lower()
    if mode in ("saml", "hybrid"):
        return True
    if mode == "oidc":
        return _oidc_group_mapping_enabled()
    return False


def assert_sso_org_configured() -> None:
    """Refuse to start a release that uses SSO without ``SSO_ORG_ID``."""
    if not sso_org_required() or _raw_sso_org():
        return
    mode = os.getenv("AUTH_MODE")
    if is_production():
        raise RuntimeError(
            f"{SSO_ORG_ENV} is unset in a production build with AUTH_MODE={mode}: "
            "set it to the id of the organization that owns this deployment's "
            "identity provider (or to 'none' until that organization exists), "
            "otherwise SSO group mappings silently stop applying; refusing to start."
        )
    logger.warning(
        "%s is unset with AUTH_MODE=%s: no SSO group mapping applies and SAML "
        "sign-in cannot link an existing member's account by email.",
        SSO_ORG_ENV,
        mode,
    )
