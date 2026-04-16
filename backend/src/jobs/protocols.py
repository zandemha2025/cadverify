"""Job queue protocol and shared data types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class JobInfo:
    job_id: str
    status: JobStatus
    result: Optional[dict] = None


class JobQueue(ABC):
    @abstractmethod
    async def enqueue(self, job_type: str, params: dict, idempotency_key: str) -> str:
        """Enqueue a job. Returns job_id. If idempotency_key already exists, returns existing job_id."""
        ...

    @abstractmethod
    async def get_status(self, job_id: str) -> JobInfo:
        """Get current job status and result if complete."""
        ...

    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """Cancel a queued job. Returns True if cancelled, False if already running/complete."""
        ...
