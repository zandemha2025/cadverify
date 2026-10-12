"""Account metadata stays bounded and the CRM payload never includes credentials."""
import pytest
import os
from pydantic import ValidationError


def test_signup_profile_validation_and_metadata_allowlist():
    from src.auth.password import SignupIn
    from src.services.customer_sync import profile_metadata
    body = SignupIn(email="lead@example.com", password="Password1", name=" Nazeem Ahmed ", phone="+1 (555) 123-4567", timezone="America/New_York", analytics_consent=True)
    assert body.name == "Nazeem Ahmed"
    assert body.phone == "+1 (555) 123-4567"
    assert SignupIn(email="a@b.com", password="Password1", utm_campaign="summer & fall").utm_campaign == ""
    assert profile_metadata(body) == {"timezone": "America/New_York", "analytics_consent": True}
    with pytest.raises(ValidationError):
        SignupIn(email="a@b.com", password="Password1", phone="call me at <script>")
    with pytest.raises(ValidationError):
        SignupIn(email="a@b.com", password="Password1", name="x" * 161)


def test_crm_payload_allowlists_fields_and_preserves_status_on_update():
    from datetime import datetime, timezone
    from src.services.customer_sync import notion_properties
    user = {"id": 42, "email": "lead@example.com", "full_name": "A Person", "phone": "+15551234567", "created_at": datetime(2026, 10, 11, tzinfo=timezone.utc), "last_seen_at": None, "auth_provider": "password", "signup_metadata": {"timezone": "America/New_York", "country": "US", "password": "SECRET"}, "password_hash": "HASH"}
    properties = notion_properties(user)
    assert properties["Account ID"]["rich_text"][0]["text"]["content"] == "scalecad-user-42"
    assert properties["Joined at"]["date"]["start"] == "2026-10-11T00:00:00+00:00"
    assert properties["Company"]["title"][0]["text"]["content"] == "A Person"
    assert properties["Contact Person"]["rich_text"][0]["text"]["content"] == "A Person"
    assert "Name" not in properties
    assert "Status" not in properties
    assert "SECRET" not in str(properties) and "HASH" not in str(properties)


@pytest.mark.asyncio
async def test_notion_retry_recovers_created_page_without_duplicates():
    from datetime import datetime, timezone
    import httpx
    from src.services.customer_sync import sync_notion_user
    page_id = "01234567-89ab-4def-8123-456789abcdef"
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": [{"id": page_id}]})
        assert request.method == "PATCH"
        assert "Status" not in request.content.decode()
        assert "Company" not in request.content.decode()
        return httpx.Response(200, json={"id": page_id})
    user = {"id": 42, "email": "lead@example.com", "full_name": None, "phone": None, "created_at": datetime.now(timezone.utc), "last_seen_at": None, "auth_provider": "oidc", "signup_metadata": {}}
    async with httpx.AsyncClient(base_url="https://api.notion.com", transport=httpx.MockTransport(handle)) as client:
        assert await sync_notion_user(client, user, page_id) == page_id
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_new_lead_uses_existing_clients_database_schema():
    from datetime import datetime, timezone
    import json
    import httpx
    from src.services.customer_sync import sync_notion_user
    page_id = "01234567-89ab-4def-8123-456789abcdef"
    data_source = "6e8703f9-0aae-8263-b7b8-070691bd03f0"
    def handle(request):
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": []})
        body = json.loads(request.content)
        assert body["parent"]["data_source_id"] == data_source
        assert body["properties"]["Status"] == {"status": {"name": "New Lead"}}
        assert body["properties"]["Company"]["title"][0]["text"]["content"] == "lead@example.com"
        assert body["properties"]["Contact Person"] == {"rich_text": []}
        return httpx.Response(200, json={"id": page_id})
    user = {"id": 42, "email": "lead@example.com", "full_name": None, "phone": None, "created_at": datetime.now(timezone.utc), "last_seen_at": None, "auth_provider": "oidc", "signup_metadata": {}}
    async with httpx.AsyncClient(base_url="https://api.notion.com", transport=httpx.MockTransport(handle)) as client:
        assert await sync_notion_user(client, user, data_source) == page_id


@pytest.mark.skipif(not os.getenv("DATABASE_URL", "").startswith("postgresql"), reason="requires Postgres")
@pytest.mark.asyncio
async def test_profile_signup_crm_retry_and_sync_with_real_postgres(monkeypatch):
    import uuid
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import text
    from src.auth.password import router
    from src.db.engine import get_session_factory, dispose_engine
    from src.services import customer_sync
    monkeypatch.setenv("RELEASE", "dev")
    monkeypatch.setenv("SIGNUP_RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("PUBLIC_PASSWORD_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("NOTION_INTEGRATION_TOKEN", "test-not-real")
    monkeypatch.setenv("NOTION_CRM_DATA_SOURCE_ID", "6e8703f9-0aae-8263-b7b8-070691bd03f0")
    app = FastAPI()
    app.include_router(router, prefix="/auth")
    uid = None
    previous_sync = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/auth/signup", json={"email": f"crm-{uuid.uuid4().hex}@example.com", "password": "Password123", "name": "A Person", "phone": "+15551234567", "timezone": "America/New_York"})
            assert response.status_code == 200, response.text
            uid = response.json()["user"]["id"]
            session = response.json()["session"]
            response = await client.post("/auth/me/profile", json={"analytics_consent": True, "timezone": "America/New_York"}, headers={"cookie": f"dash_session={session}"})
            assert response.status_code == 200, response.text
            assert (await client.post("/auth/me/profile", json={})).status_code == 401
        async with get_session_factory()() as db:
            row = (await db.execute(text("SELECT full_name, phone, signup_metadata FROM users WHERE id=:id"), {"id": uid})).first()
            assert row[0:2] == ("A Person", "+15551234567")
            assert row[2] == {"timezone": "America/New_York", "analytics_consent": True}
            # Restore other fixtures after temporarily isolating this queue.
            previous_sync = (await db.execute(text("SELECT id, crm_sync_after::text FROM users WHERE id != :id"), {"id": uid})).all()
            await db.execute(text("UPDATE users SET crm_sync_after='infinity' WHERE id != :id"), {"id": uid})
            await db.commit()
        async def fail(*args):
            raise httpx.ConnectError("provider unavailable")
        monkeypatch.setattr(customer_sync, "sync_notion_user", fail)
        await customer_sync.sync_customer_accounts({})
        async with get_session_factory()() as db:
            retry = (await db.execute(text("SELECT notion_page_id, crm_sync_after > now() FROM users WHERE id=:id"), {"id": uid})).first()
            assert retry[0] is None and retry[1]
            await db.execute(text("UPDATE users SET crm_sync_after=now() WHERE id=:id"), {"id": uid})
            await db.commit()
        async def succeed(client, user, source):
            assert "password" not in user and "password_hash" not in user
            return "01234567-89ab-4def-8123-456789abcdef"
        monkeypatch.setattr(customer_sync, "sync_notion_user", succeed)
        await customer_sync.sync_customer_accounts({})
        async with get_session_factory()() as db:
            assert await db.scalar(text("SELECT notion_page_id FROM users WHERE id=:id"), {"id": uid}) == "01234567-89ab-4def-8123-456789abcdef"
    finally:
        if uid:
            async with get_session_factory()() as db:
                for other_id, sync_after in previous_sync:
                    await db.execute(text("UPDATE users SET crm_sync_after=CAST(:after AS timestamptz) WHERE id=:id"), {"id": other_id, "after": sync_after})
                await db.execute(text("DELETE FROM audit_log WHERE user_id=:id"), {"id": uid})
                await db.execute(text("DELETE FROM users WHERE id=:id"), {"id": uid})
                await db.commit()
        await dispose_engine()
