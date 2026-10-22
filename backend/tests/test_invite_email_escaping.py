"""The org invite email escapes the organization name and link in its HTML."""
from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture()
def sent(monkeypatch):
    messages: list[dict] = []
    fake = types.ModuleType("resend")
    fake.Emails = types.SimpleNamespace(send=lambda payload: messages.append(payload))
    monkeypatch.setitem(sys.modules, "resend", fake)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("RESEND_FROM", "ScaleCAD <noreply@example.com>")
    return messages


def test_org_name_is_escaped_in_the_invite_html(sent):
    from src.api.org_routes import _send_invite_email

    name = '<img src=x onerror="alert(1)"> Acme & Co'
    assert _send_invite_email("a@example.com", "https://app.example.com/orgs/accept?token=abc", name)
    html = sent[0]["html"]
    assert "<img" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; Acme &amp; Co" in html


def test_invite_link_is_escaped_as_an_attribute(sent):
    from src.api.org_routes import _send_invite_email

    assert _send_invite_email("a@example.com", 'https://app.example.com/orgs/accept?token=a"b&c=1', None)
    html = sent[0]["html"]
    assert 'href="https://app.example.com/orgs/accept?token=a&quot;b&amp;c=1"' in html


def test_plain_invite_reads_as_before(sent):
    from src.api.org_routes import _send_invite_email

    assert _send_invite_email("a@example.com", "https://app.example.com/orgs/accept?token=abc", "Acme")
    html = sent[0]["html"]
    assert html.startswith("<p>You've been invited to Acme.</p>")
    assert '<a href="https://app.example.com/orgs/accept?token=abc">Accept the invitation</a>' in html


def test_an_invite_names_who_sent_it_the_organization_and_the_run(sent):
    # oo-18: "You've been invited." with no inviter, no org and no link to the run read as spam.
    from src.api.org_routes import _invite_link, _safe_next, _send_invite_email

    link = _invite_link("abc", _safe_next("/app/many/01M5H5DZATJCQAN6SMMTGCCYD7"))
    assert link.endswith("/orgs/accept?token=abc&next=/app/many/01M5H5DZATJCQAN6SMMTGCCYD7")
    assert _send_invite_email("mark@ridgeline.com", link, "Ridgeline <Fluid> Systems",
                              inviter="Dana Ruiz (dana@ridgeline.com)", role="a viewer",
                              what="It's to look at a make-or-buy result: Ridgeline-bought-parts.")
    msg = sent[0]
    assert msg["subject"] == "Dana Ruiz (dana@ridgeline.com) invited you to Ridgeline <Fluid> Systems on ScaleCAD"
    assert msg["html"].startswith("<p>Dana Ruiz (dana@ridgeline.com) invited you to Ridgeline &lt;Fluid&gt; Systems on ScaleCAD as a viewer.</p>")
    assert "make-or-buy result: Ridgeline-bought-parts" in msg["html"]
    assert ">Accept and open it</a>" in msg["html"]


def test_an_invite_opens_only_a_page_in_the_app():
    from src.api.org_routes import _safe_next

    assert _safe_next("/app/many/01M5H5DZATJCQAN6SMMTGCCYD7") == "/app/many/01M5H5DZATJCQAN6SMMTGCCYD7"
    for bad in ("https://evil.example/app/x", "//evil.example", "/app//x", "/login?next=x", "/app/../x", None, ""):
        assert _safe_next(bad) is None
