"""Retryable account-to-Notion sync; committed user rows are the durable queue."""
from __future__ import annotations

import logging
import asyncio
import os
from uuid import UUID

import httpx
from sqlalchemy import text

from src.db.engine import get_session_factory

logger = logging.getLogger("cadverify.customer_sync")


def profile_metadata(body) -> dict:
    fields = ("timezone", "analytics_consent", "utm_source", "utm_medium", "utm_campaign")
    return {key: getattr(body, key) for key in fields if getattr(body, key, None)}


def notion_properties(user: dict) -> dict:
    metadata = user["signup_metadata"] or {}
    properties = {}
    for name, value in {
        "Account ID": f"scalecad-user-{user['id']}", "Auth provider": user["auth_provider"],
        "Timezone": metadata.get("timezone"), "Source": metadata.get("utm_source"),
        "Campaign": metadata.get("utm_campaign"), "Country": metadata.get("country"),
        "Region": metadata.get("region"), "City": metadata.get("city"),
    }.items():
        properties[name] = {"rich_text": [{"text": {"content": str(value)[:200]}}] if value else []}
    properties["Company"] = {"title": [{"text": {"content": user["full_name"] or user["email"]}}]}
    properties["Contact Person"] = {"rich_text": [{"text": {"content": user["full_name"]}}] if user["full_name"] else []}
    properties["Email"] = {"email": user["email"]}
    properties["Phone"] = {"phone_number": user["phone"] or None}
    for name, column in (("Joined at", "created_at"), ("Last seen", "last_seen_at")):
        value = user[column]
        properties[name] = {"date": {"start": value.isoformat()} if value else None}
    return properties


async def sync_notion_user(client: httpx.AsyncClient, user: dict, data_source: str) -> str:
    properties = notion_properties(user)
    page_id = user.get("notion_page_id")
    if not page_id:
        # An accepted create can lose its response. Recover by account ID before retrying.
        response = await client.post(f"/v1/data_sources/{data_source}/query", json={
            "filter": {"property": "Account ID", "rich_text": {"equals": f"scalecad-user-{user['id']}"}}, "page_size": 1,
        })
        response.raise_for_status()
        await asyncio.sleep(0.4)
        results = response.json().get("results", [])
        page_id = results[0]["id"] if results else None
    if page_id:
        page_id = str(UUID(page_id))
        # Keep a company name entered by sales after the individual lead was created.
        properties.pop("Company")
        response = await client.patch(f"/v1/pages/{page_id}", json={"properties": properties})
    else:
        response = await client.post("/v1/pages", json={
            "parent": {"type": "data_source_id", "data_source_id": data_source},
            "properties": {**properties, "Status": {"status": {"name": "New Lead"}}},
        })
    response.raise_for_status()
    await asyncio.sleep(0.4)
    return str(UUID(response.json()["id"]))


def _notion_client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://api.notion.com", timeout=10, headers={
        "Authorization": f"Bearer {token}", "Notion-Version": "2025-09-03",
    })


async def archive_notion_user(user_id: int, page_id: str | None) -> bool:
    """Move a deleted account's customer-list page to Notion's trash.

    Called by account deletion (a resumable step, retried until it succeeds).
    False when the CRM isn't configured here; True when the page is in the
    trash or there was none. Finds the page by its Account ID when the account
    never stored one (a lost create response).
    """
    token = os.getenv("NOTION_INTEGRATION_TOKEN", "").strip()
    data_source = os.getenv("NOTION_CRM_DATA_SOURCE_ID", "").strip()
    if not token or not data_source:
        return False
    data_source = str(UUID(data_source))
    async with _notion_client(token) as client:
        if not page_id:
            response = await client.post(f"/v1/data_sources/{data_source}/query", json={
                "filter": {"property": "Account ID", "rich_text": {"equals": f"scalecad-user-{int(user_id)}"}},
                "page_size": 1,
            })
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                return True
            page_id = results[0]["id"]
        response = await client.patch(f"/v1/pages/{UUID(str(page_id))}", json={"in_trash": True})
        if response.status_code == 404:
            return True
        response.raise_for_status()
    return True


async def sync_customer_accounts(ctx: dict) -> None:
    token = os.getenv("NOTION_INTEGRATION_TOKEN", "").strip()
    data_source = os.getenv("NOTION_CRM_DATA_SOURCE_ID", "").strip()
    if not token or not data_source:
        return
    try:
        data_source = str(UUID(data_source))
    except ValueError:
        logger.error("Notion CRM data source configuration is invalid")
        return
    async with httpx.AsyncClient(base_url="https://api.notion.com", timeout=10, headers={
        "Authorization": f"Bearer {token}", "Notion-Version": "2025-09-03",
    }) as client:
        # One row per transaction: an HTTP timeout cannot roll back another lead's sync.
        for _ in range(10):
            async with get_session_factory()() as session:
                row = (await session.execute(text(
                    "SELECT id, email, full_name, phone, auth_provider, created_at, last_seen_at, "
                    "signup_metadata, notion_page_id FROM users "
                    "WHERE is_active AND crm_sync_after <= now() "
                    "ORDER BY crm_sync_after, id LIMIT 1 FOR UPDATE SKIP LOCKED"
                ))).mappings().first()
                if row is None:
                    return
                try:
                    page_id = await sync_notion_user(client, dict(row), data_source)
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    # Do not log provider bodies, headers, email, phone or tokens.
                    logger.warning("Notion CRM sync failed; retry scheduled")
                    await session.execute(text("UPDATE users SET crm_sync_after = now() + interval '5 minutes' WHERE id = :id"), {"id": row["id"]})
                    await session.commit()
                    return
                await session.execute(text(
                    "UPDATE users SET notion_page_id = :page, crm_sync_after = 'infinity'::timestamptz WHERE id = :id"
                ), {"id": row["id"], "page": page_id})
                await session.commit()
