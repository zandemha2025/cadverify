"""Worker side of data deletion: finish removing stored files, and sweep.

The API removes a deletion's stored files right after its database commit.
Whatever did not finish (a crash, an object-store outage, a large org) is
picked up here: ``run_data_deletion`` is enqueued by the API, and the cron
``sweep_data_deletions`` re-offers every receipt idle past its lease plus the
organization receipts due their final pass. Every step is idempotent.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("cadverify.jobs.data_deletion")


async def run_data_deletion(ctx: dict, deletion_ulid: str) -> dict:
    from src.services import data_deletion_service as svc

    row = await svc.process(deletion_ulid, force=False)
    if row is None:
        return {"deletion_id": deletion_ulid, "status": "not_claimed"}
    return {"deletion_id": deletion_ulid, "status": row.status, "steps_done": row.steps_done}


async def sweep_data_deletions(ctx: dict) -> dict:
    from src.db.engine import get_session_factory
    from src.services import data_deletion_service as svc

    async with get_session_factory()() as session:
        stale, sweeps = await svc.pending_deletions(session)
    processed = swept = 0
    for ulid in stale:
        try:
            if await svc.process(ulid, force=False) is not None:
                processed += 1
        except Exception:  # noqa: BLE001 - one receipt never blocks the rest
            logger.exception("data deletion %s retry failed", ulid)
    for ulid in sweeps:
        try:
            if await svc.final_sweep(ulid) is not None:
                swept += 1
        except Exception:  # noqa: BLE001
            logger.exception("data deletion %s final sweep failed", ulid)
    return {"processed": processed, "final_sweeps": swept}
