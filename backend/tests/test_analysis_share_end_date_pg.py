"""A check's share link takes a chosen end date, as record and package links do (R2, minor).

``POST /analyses/{id}/share`` accepted ``{"expires_on": "YYYY-MM-DD"}`` (the
body is ``ShareOptions``) but used only ``expires_in_days``, so the link lasted
the default 7 days whatever date the sharer picked. It now honours the date
within the same bounds as the other share routes: today up to a year ahead,
the link working through that day (UTC); a past date or one more than a year
out is refused.

Skipped unless DATABASE_URL points at Postgres migrated to head.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not _PG, reason="requires live Postgres")]

from tests.test_data_deletion_pg import _act, _app, _cleanup, _world, stores  # noqa: E402,F401


async def test_a_check_link_lasts_until_the_chosen_day(stores):  # noqa: F811 - the imported fixture
    from httpx import ASGITransport, AsyncClient

    w = await _world(stores)
    analysis = w.parts["Q"]["analysis"]
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["owner"])
            # The seeded link is on; switch it off so the next share makes a new one.
            assert (await client.delete(f"/api/v1/analyses/{analysis}/share")).status_code == 200

            today = datetime.now(timezone.utc).date()
            past = await client.post(f"/api/v1/analyses/{analysis}/share",
                                     json={"expires_on": (today - timedelta(days=1)).isoformat()})
            assert past.status_code == 422, past.text
            too_far = await client.post(f"/api/v1/analyses/{analysis}/share",
                                        json={"expires_on": (today + timedelta(days=366)).isoformat()})
            assert too_far.status_code == 422, too_far.text

            chosen = today + timedelta(days=12)
            made = await client.post(f"/api/v1/analyses/{analysis}/share", json={"expires_on": chosen.isoformat()})
            assert made.status_code == 200, made.text
            ends = datetime.fromisoformat(made.json()["share_expires_at"])
            assert ends == datetime.combine(chosen, datetime.min.time(), tzinfo=timezone.utc).replace(
                hour=23, minute=59, second=59)
            assert (await client.get(made.json()["share_url"])).status_code == 200

            # The last day allowed (a year ahead, as on the record route) works too.
            assert (await client.delete(f"/api/v1/analyses/{analysis}/share")).status_code == 200
            last = today + timedelta(days=365)
            made = await client.post(f"/api/v1/analyses/{analysis}/share", json={"expires_on": last.isoformat()})
            assert made.status_code == 200, made.text
            assert datetime.fromisoformat(made.json()["share_expires_at"]).date() == last
            # A plain number of days still works.
            assert (await client.delete(f"/api/v1/analyses/{analysis}/share")).status_code == 200
            made = await client.post(f"/api/v1/analyses/{analysis}/share", json={"expires_in_days": 30})
            left = datetime.fromisoformat(made.json()["share_expires_at"]) - datetime.now(timezone.utc)
            assert timedelta(days=29, hours=23) < left <= timedelta(days=30)
    finally:
        await _cleanup(w)
