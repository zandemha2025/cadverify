"""SSRF guard for user-supplied outbound URLs (webhooks).

A webhook_url is attacker-controlled: without validation it can be pointed at
internal services (link-local metadata endpoints, loopback admin panels,
RFC-1918 hosts) turning our egress into a server-side request forgery oracle.

`validate_outbound_url` enforces http(s)-only and resolves the host, rejecting
any URL that resolves to a private / loopback / link-local / reserved range
(incl. the 169.254.169.254 cloud metadata address and IPv6 fc00::/7 / ::1).

Validation runs twice: at request time (batch creation → 400) and again at
delivery time as defense-in-depth, since DNS can be rebound between the two.

Off-switch: WEBHOOK_SSRF_GUARD_ENABLED=0 disables the guard entirely (default
on). It exists only for closed-network operators who deliberately deliver to
RFC-1918 hosts; leaving it on is strongly recommended.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit


class UnsafeURLError(ValueError):
    """Raised when a URL is rejected by the SSRF guard."""


_ALLOWED_SCHEMES = frozenset({"http", "https"})


def guard_enabled() -> bool:
    """Whether the SSRF guard is active (default on)."""
    return os.getenv("WEBHOOK_SSRF_GUARD_ENABLED", "1") != "0"


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    """True if the address falls in a range we must never egress to.

    Covers loopback (127/8, ::1), private (10/8, 172.16/12, 192.168/16,
    fc00::/7), link-local (169.254/16 incl. 169.254.169.254, fe80::/10),
    unspecified (0.0.0.0, ::), multicast, and other reserved ranges. IPv4
    addresses mapped into IPv6 (::ffff:127.0.0.1) are unwrapped first.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
    )


def _resolve_ips(host: str) -> list[ipaddress._BaseAddress]:
    """Resolve a hostname to every A/AAAA address, or parse an IP literal.

    Raises UnsafeURLError when the host cannot be resolved (a webhook we can
    never reach is not one we should accept).
    """
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"host does not resolve: {host}") from exc

    ips: list[ipaddress._BaseAddress] = []
    for info in infos:
        addr = info[4][0]
        # Strip IPv6 scope id (fe80::1%eth0) before parsing.
        addr = addr.split("%", 1)[0]
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    if not ips:
        raise UnsafeURLError(f"host does not resolve to an IP: {host}")
    return ips


def validate_outbound_url(url: str | None) -> None:
    """Validate a user-supplied outbound URL, raising UnsafeURLError if unsafe.

    No-op when the guard is disabled or the URL is falsy. Enforces http(s)
    scheme, a present host, and that EVERY resolved address is a public,
    routable one.
    """
    if not url or not guard_enabled():
        return

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"URL scheme must be http or https, got '{parts.scheme or '(none)'}'"
        )

    host = parts.hostname
    if not host:
        raise UnsafeURLError("URL has no host")

    for ip in _resolve_ips(host):
        if _ip_is_blocked(ip):
            raise UnsafeURLError(
                f"URL host '{host}' resolves to a non-routable address ({ip})"
            )


def is_safe_outbound_url(url: str | None) -> bool:
    """Boolean convenience wrapper around validate_outbound_url."""
    try:
        validate_outbound_url(url)
        return True
    except UnsafeURLError:
        return False
