"""arq queue payloads are JSON on both sides; a pickled payload never runs.

Jobs carry ids, so the API's enqueue pool and the worker both use the JSON
job serializer. A payload in Redis that is not JSON (for example a pickle) is
refused by the worker's deserializer and its function is never called.
"""
from __future__ import annotations

import asyncio
import pickle

import fakeredis
import pytest
import redis.asyncio
from arq import func
from arq.connections import ArqRedis
from arq.jobs import DeserializationError, deserialize_job_raw, serialize_job
from arq.worker import Worker, get_kwargs

from src.jobs import arq_backend
from src.jobs.arq_backend import job_deserializer, job_serializer


def _pool(server, *, json: bool) -> ArqRedis:
    connections = redis.asyncio.ConnectionPool(
        connection_class=fakeredis.aioredis.FakeConnection, server=server
    )
    if json:
        return ArqRedis(connections, job_serializer=job_serializer, job_deserializer=job_deserializer)
    return ArqRedis(connections)  # arq's default: pickle


def test_worker_settings_use_the_json_serializer():
    from src.jobs.worker import WorkerSettings

    kwargs = get_kwargs(WorkerSettings)
    assert kwargs["job_serializer"] is job_serializer
    assert kwargs["job_deserializer"] is job_deserializer


@pytest.mark.asyncio
async def test_api_enqueue_pool_uses_the_json_serializer(monkeypatch):
    seen = {}

    async def fake_create_pool(settings, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(arq_backend, "_pool", None)
    monkeypatch.setattr(arq_backend, "create_pool", fake_create_pool)
    await arq_backend.get_arq_pool()
    assert seen["job_serializer"] is job_serializer
    assert seen["job_deserializer"] is job_deserializer
    monkeypatch.setattr(arq_backend, "_pool", None)


def test_json_round_trip_keeps_the_job_ids():
    raw = serialize_job("run_stored_check", ("01JOBULID",), {}, 1, 1700000000000, serializer=job_serializer)
    assert raw.startswith(b"{")
    fn, args, kwargs, tries, et = deserialize_job_raw(raw, deserializer=job_deserializer)
    assert (fn, list(args), kwargs, tries, et) == ("run_stored_check", ["01JOBULID"], {}, 1, 1700000000000)


def test_a_pickled_payload_is_refused_by_the_deserializer():
    raw = serialize_job("run_stored_check", ("01JOBULID",), {}, 1, 1700000000000)
    assert raw == pickle.dumps(pickle.loads(raw))  # arq's default is pickle
    with pytest.raises(DeserializationError):
        deserialize_job_raw(raw, deserializer=job_deserializer)
    with pytest.raises(DeserializationError):
        deserialize_job_raw(pickle.dumps({"f": "x"}, protocol=0), deserializer=job_deserializer)


@pytest.mark.asyncio
async def test_the_worker_never_runs_a_pickled_job_and_runs_a_json_one(monkeypatch):
    async def _no_info(*_a, **_k):  # fakeredis has no INFO command
        return None

    monkeypatch.setattr("arq.worker.log_redis_info", _no_info)
    server = fakeredis.FakeServer()
    calls: list = []

    async def probe(ctx, job_id):
        calls.append(job_id)
        return {"job": job_id}

    legacy = _pool(server, json=False)
    current = _pool(server, json=True)
    await legacy.enqueue_job("probe", "PICKLED", _job_id="pickled-job")
    await current.enqueue_job("probe", "JSON", _job_id="json-job")

    worker = Worker(
        functions=[func(probe, name="probe")],
        redis_pool=current,
        burst=True,
        poll_delay=0.01,
        handle_signals=False,
        job_serializer=job_serializer,
        job_deserializer=job_deserializer,
        max_tries=1,
    )
    await asyncio.wait_for(worker.async_run(), timeout=20)
    await worker.close()
    assert calls == ["JSON"]
    assert worker.jobs_failed == 1 and worker.jobs_complete == 1
