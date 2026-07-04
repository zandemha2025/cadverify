"""Deploy one-shot: backfill the part-summary projection (Aramco GAP 2).

Populates ``part_summaries`` from every existing analysis / cost decision so the
whole-inventory triage COUNT and the keyset-paginated grid serve the UNCAPPED
scaled path. Idempotent — safe to re-run; re-running changes nothing.

Correctness does NOT depend on this: the triage endpoint falls back to the
legacy capped fold (honest ``truncated:true``) for any org whose projection is
still cold, and the persist hooks maintain the projection for all NEW writes.
This backfill lifts the cap for PRE-EXISTING data; run it once after deploying
migration ``0019_part_summaries``.

    DATABASE_URL=postgresql://… python -m scripts.backfill_part_summaries

Commits in one transaction after the full backfill completes.
"""
from __future__ import annotations

import asyncio
import logging

import src.db.engine as eng
from src.services import part_summary_service

logger = logging.getLogger("cadverify.backfill_part_summaries")


async def main() -> int:
    """Backfill every org's projection; return the number of parts upserted."""
    await eng.init_engine()
    try:
        async with eng.get_session_factory()() as session:
            count = await part_summary_service.backfill_part_summaries(session)
            await session.commit()
        logger.info("part-summary backfill complete: %d parts upserted", count)
        print(f"part-summary backfill complete: {count} parts upserted")
        return count
    finally:
        await eng.dispose_engine()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
