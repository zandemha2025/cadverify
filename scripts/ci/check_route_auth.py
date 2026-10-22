#!/usr/bin/env python3
"""Verify every route in backend/src/api/ and backend/src/auth/ declares an auth dependency.

Globs EVERY module under ``backend/src/api/`` and ``backend/src/auth/`` that
defines an ``APIRouter`` (not just ``routes.py``) and, for each route function,
confirms it declares an auth
dependency — ``require_api_key`` / ``require_role`` / ``require_org_role`` /
``require_role_and_org_role`` / ``require_dashboard_session`` — either directly
in the function signature or via the route decorator's ``dependencies=[...]``.
Module-level aliases of those factories (e.g.
``require_admin = require_org_role(OrgRole.admin)``) are resolved per module so
an aliased gate still counts as auth.

Any route WITHOUT auth must appear in the explicit per-module ``PUBLIC_ALLOWLIST``
below (the intentional public surface; auth modules are keyed ``auth/<file>``).
An un-allowlisted public route in ANY scanned module exits nonzero — this is the guard that keeps a new router from silently
shipping an unauthenticated endpoint (the original check only ever parsed
``routes.py`` and was blind to the nine newer routers).
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "backend/src/api"
AUTH_DIR = ROOT / "backend/src/auth"
# Every directory whose routers are checked: the API routers and the sign-in /
# key-management routers under src/auth.
ROUTER_DIRS = [API_DIR, AUTH_DIR]

# Auth-dependency factories (or the AuthedUser/context dep) that gate a route.
AUTH_DEPENDENCIES = {
    "require_api_key",
    "require_role",
    "require_org_role",
    "require_role_and_org_role",
    # The shared tenant-write gates (analyst + org member), src/auth/rbac.py.
    "require_org_writer",
    "require_org_checker",
    "require_dashboard_session",
}

# The ONLY intentionally-public routes, keyed by module file name. Anything public
# and not listed here fails the check. Paths are decorator-relative (no mount
# prefix), matching how they are written in source.
PUBLIC_ALLOWLIST: dict[str, set[tuple[str, str]]] = {
    "metrics.py": {
        # Prometheus scrape target. UNAUTHENTICATED by design (scrapers carry no
        # API key); additionally gated by METRICS_ENABLED and meant to be scraped
        # over a private network / ingress allowlist. Payload is machine metrics
        # only (no PII/secrets).
        ("get", "/metrics"),
    },
    "health.py": {
        # Liveness/readiness probe — no secrets, must answer before auth is ready.
        ("get", "/health"),
        # Deep dependency health (DB/Redis/worker-heartbeat/queue-depth). Same
        # public-probe rationale as /health: no PII/secrets, machine-readable
        # dependency posture only (booleans, states, counts) so orchestrators
        # and readiness gates can poll it before auth is available.
        ("get", "/health/deep"),
    },
    "cost_decisions.py": {
        # Sanitized public cost-share view (share-link only, no PII/provenance).
        ("get", "/cost/{short_id}"),
    },
    "share.py": {
        # Sanitized public analysis-share view (share-link only; noindex/no-store).
        ("get", "/{short_id}"),
    },
    "billing.py": {
        # Public plan facts for the pricing page: tier sizes and the Pro price.
        # No account data.
        ("get", "/plans"),
        # Stripe webhook. Authenticated by the Stripe-Signature HMAC (verified
        # before any write), not by a ScaleCad session or API key.
        ("post", "/stripe-webhook"),
    },
    # ── src/auth: sign-in flows a visitor uses before any session exists ──
    "auth/magic_link.py": {
        # Send a sign-in link (rate-limited, bot-checked), exchange its one-time
        # token for a session, and the emailed link's own landing.
        ("post", "/magic/start"),
        ("post", "/magic/exchange"),
        ("get", "/magic/verify"),
    },
    "auth/oauth.py": {
        # Google sign-in: start, and the state-checked provider callback.
        ("get", "/google/start"),
        ("get", "/google/callback"),
    },
    "auth/oidc.py": {
        # Whether OIDC sign-in is configured (no account data), its start, and
        # the PKCE/state/nonce-checked provider callback.
        ("get", "/status"),
        ("get", "/login"),
        ("get", "/callback"),
    },
    "auth/password.py": {
        # Deploy probe authenticated by the signed frontend-proxy handshake.
        ("get", "/proxy-health"),
        # Public pilot intake (rate-limited, bot-checked).
        ("post", "/pilot-request"),
        # Password sign-up and sign-in (rate-limited, timing-equalised).
        ("post", "/signup"),
        ("post", "/login"),
        # Ends the caller's own browser session.
        ("post", "/logout"),
        # CRM geo webhook authenticated by its own bearer token.
        ("post", "/crm/location"),
    },
    "auth/password_reset.py": {
        # Request a reset email; complete with the single-use emailed token.
        ("post", "/password/reset/start"),
        ("post", "/password/reset/complete"),
    },
    "auth/saml.py": {
        # SAML SP endpoints the IdP and browser reach before a session exists:
        # start, assertion consumer (signature-checked), single logout, and the
        # public SP metadata.
        ("get", "/login"),
        ("post", "/acs"),
        ("get", "/logout"),
        ("get", "/metadata"),
    },
    "corpus_router.py": {
        # DEV-ONLY labeling tool: mounted solely under LABELING_ENABLED=1 and
        # localhost-only by design; never ships to production. Public by intent.
        ("get", "/parts"),
        ("get", "/parts/{part_id}"),
        ("get", "/parts/{part_id}/mesh.stl"),
        ("post", "/labels"),
        ("get", "/progress"),
    },
}

_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def router_names(tree: ast.AST) -> set[str]:
    """Names bound to an ``APIRouter(...)`` instance in this module."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if call_name(node.value.func) == "APIRouter":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
    return names


def auth_aliases(tree: ast.AST) -> set[str]:
    """Module-level names aliasing an auth factory, e.g.
    ``require_admin = require_org_role(OrgRole.admin)`` — so an aliased gate still
    counts as auth."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        rhs = node.value
        rhs_name = None
        if isinstance(rhs, ast.Call):
            rhs_name = call_name(rhs.func)
        elif isinstance(rhs, (ast.Name, ast.Attribute)):
            rhs_name = call_name(rhs)
        if rhs_name in AUTH_DEPENDENCIES:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases.add(target.id)
    return aliases


def route_decorators(fn: ast.AST, rnames: set[str]) -> Iterable[tuple[str, str]]:
    for decorator in getattr(fn, "decorator_list", []):
        if not isinstance(decorator, ast.Call):
            continue
        if not isinstance(decorator.func, ast.Attribute):
            continue
        if not isinstance(decorator.func.value, ast.Name):
            continue
        if decorator.func.value.id not in rnames:
            continue
        method = decorator.func.attr
        if method not in _HTTP_METHODS:
            continue
        if not decorator.args:
            continue
        path_arg = decorator.args[0]
        if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str):
            yield method, path_arg.value


def depends_on_auth(node: ast.AST, auth_names: set[str]) -> bool:
    if not isinstance(node, ast.Call) or call_name(node.func) != "Depends":
        return False
    if not node.args:
        return False
    dependency = node.args[0]
    name = call_name(dependency)
    if name in auth_names:
        return True
    if isinstance(dependency, ast.Call):
        return call_name(dependency.func) in auth_names
    return False


def function_declares_auth(fn: ast.AST, auth_names: set[str]) -> bool:
    # ast.walk(fn) covers both the signature defaults (Depends(...) params) AND the
    # decorator's dependencies=[...] list, so either wiring counts.
    return any(depends_on_auth(node, auth_names) for node in ast.walk(fn))


def allowlist_key(module: Path) -> str:
    """API modules are keyed by file name; any other directory as ``<dir>/<file>``."""
    return module.name if module.parent == API_DIR else f"{module.parent.name}/{module.name}"


def main() -> int:
    modules = [m for d in ROUTER_DIRS for m in sorted(Path(d).glob("*.py"))]
    if not modules:
        print(f"No router modules found under {', '.join(str(d) for d in ROUTER_DIRS)}")
        return 1

    failures: list[str] = []
    checked = 0
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        rnames = router_names(tree)
        if not rnames:
            continue
        auth_names = AUTH_DEPENDENCIES | auth_aliases(tree)
        key = allowlist_key(module)
        allow = PUBLIC_ALLOWLIST.get(key, set())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for method, path in route_decorators(node, rnames):
                checked += 1
                if (method, path) in allow:
                    continue
                if not function_declares_auth(node, auth_names):
                    failures.append(
                        f"{key}: {method.upper()} {path} -> {node.name}"
                    )

    if failures:
        print("Route auth coverage failed (un-allowlisted public route):")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"route-auth-coverage OK ({checked} routes across api and auth modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
