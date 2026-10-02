"""Real PostgreSQL checks for lifetime credits, races and refunds.

Run with DATABASE_URL pointing at a local/CI PostgreSQL. Each test creates and
removes its own isolated schema; no existing application rows are touched.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.auth import validation_caps as vc
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.models import TrialCheck


@pytest_asyncio.fixture
async def ledger(monkeypatch):
    url = os.environ.get('DATABASE_URL', '')
    assert url.startswith('postgresql'), 'Set DATABASE_URL to local/CI PostgreSQL to test the product allowance.'
    url = url.replace('postgresql://', 'postgresql+asyncpg://', 1)
    schema = 'trial_test_' + uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_async_engine(url, connect_args={'server_settings': {'search_path': schema}})
    try:
        async with engine.begin() as connection:
            await connection.execute(text('CREATE TABLE users (id bigint PRIMARY KEY, plan text NOT NULL)'))
            await connection.execute(text('CREATE TABLE evidence (user_id bigint REFERENCES users(id) DEFERRABLE INITIALLY DEFERRED)'))
            await connection.run_sync(TrialCheck.__table__.create)
            await connection.execute(text("INSERT INTO users VALUES (1, 'trial'), (2, 'trial'), (3, 'pilot')"))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(vc, 'get_session_factory', lambda: factory)
        yield factory
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        await admin.dispose()


@pytest.mark.asyncio
async def test_lifetime_bundle_race_refund_and_account_isolation(ledger):
    # Eight completed checks plus one in-flight check leaves exactly one slot,
    # even when sixteen requests arrive concurrently on separate connections.
    for _ in range(8):
        check = str(uuid4())
        assert await vc.reserve_check(1, check, 'file', 'analysis')
        await vc.finish_check(1, check, 'analysis', True)
    pending = str(uuid4())
    await vc.reserve_check(1, pending, 'file', 'analysis')
    ids = [str(uuid4()) for _ in range(16)]
    results = await asyncio.gather(*(vc.reserve_check(1, check, 'file', 'analysis') for check in ids), return_exceptions=True)
    assert results.count(True) == 1
    rejected = [result for result in results if result is not True]
    assert all(isinstance(result, vc.HTTPException) and result.status_code == 403 for result in rejected)
    assert (await vc.user_trial_usage(1))['remaining'] == 0
    # The tenth check can still finish its own cost and preview, never an
    # eleventh check. Changing its file or repeating a successful step is denied.
    last = ids[results.index(True)]
    await vc.finish_check(1, last, 'analysis', True)
    for op in ('cost', 'preview'):
        await vc.reserve_check(1, last, 'file', op)
        await vc.finish_check(1, last, op, True)
        with pytest.raises(vc.HTTPException) as duplicate:
            await vc.reserve_check(1, last, 'file', op)
        assert duplicate.value.status_code == 409
    with pytest.raises(vc.HTTPException) as changed:
        await vc.reserve_check(1, last, 'different', 'preview-analysis')
    assert changed.value.detail['code'] == 'check_file_mismatch'
    await vc.finish_check(1, pending, 'analysis', False)
    assert (await vc.user_trial_usage(1))['remaining'] == 1
    await vc.reserve_check(1, pending, 'file', 'analysis')
    await vc.finish_check(1, pending, 'analysis', True)
    assert (await vc.user_trial_usage(1))['used'] == 10
    assert await vc.reserve_check(2, last, 'other-file', 'analysis')
    assert not await vc.reserve_check(3, last, 'file', 'analysis')
    assert (await vc.user_trial_usage(3))['unlimited']
    # Lifetime completion survives expiry; idle previews release reservations.
    async with ledger() as session, session.begin():
        await session.execute(update(TrialCheck).where(TrialCheck.user_id == 1).values(created_at=datetime.now(timezone.utc) - timedelta(days=90)))
    assert (await vc.user_trial_usage(1))['remaining'] == 0
    with pytest.raises(vc.HTTPException):
        await vc.reserve_check(1, str(uuid4()), 'file', 'analysis')


@pytest.mark.asyncio
async def test_http_bundle_success_failure_replay_and_fail_closed(ledger, monkeypatch):
    app = FastAPI()
    router = APIRouter(route_class=vc.MeteredRoute)
    calls = []

    @router.post('/validate')
    @router.post('/validate/cost')
    @router.post('/validate/preview-mesh')
    async def compute(request: Request, _: None = Depends(vc.enforce_validation_caps)):
        calls.append(request.url.path)
        if request.query_params.get('fail'):
            return JSONResponse({'error': 'invalid CAD'}, status_code=400)
        return {'result': 'computed'}

    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=1, api_key_id=0, key_prefix='session')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        async def post(path, check, data=b'CAD'):
            return await client.post(path, headers={'x-part-check-id': check}, files={'file': ('part.stp', data)})
        check = str(uuid4())
        assert (await post('/validate?fail=1', check)).status_code == 400
        assert (await vc.user_trial_usage(1))['remaining'] == 10
        assert (await post('/validate/preview-mesh', check)).status_code == 200
        assert (await vc.user_trial_usage(1))['reserved'] == 1
        assert (await post('/validate', check)).status_code == 200
        assert (await post('/validate/cost', check)).status_code == 200
        assert (await vc.user_trial_usage(1))['used'] == 1
        assert (await post('/validate', check)).status_code == 409
        assert (await post('/validate', str(uuid4()), b'')).status_code == 400
        assert (await post('/validate', 'not-a-uuid')).status_code == 400
        assert len(calls) == 4
        # A real DB query failure blocks compute rather than spending unchecked.
        async def unavailable(*args):
            raise vc.SQLAlchemyError('database unavailable')
        monkeypatch.setattr(vc, '_counts', unavailable)
        assert (await post('/validate', str(uuid4()))).status_code == 503
        assert len(calls) == 4


@pytest.mark.asyncio
async def test_paid_tools_require_operator_approval_and_stale_previews_expire(ledger):
    user = AuthedUser(user_id=1, api_key_id=0, key_prefix='session')
    with pytest.raises(vc.HTTPException) as denied:
        await vc.require_paid_access(user)
    assert denied.value.status_code == 403
    assert denied.value.detail['code'] == 'paid_access_required'
    await vc.require_paid_access(AuthedUser(user_id=3, api_key_id=0, key_prefix='session'))
    preview, active = str(uuid4()), str(uuid4())
    await vc.reserve_check(1, preview, 'file', 'preview')
    await vc.finish_check(1, preview, 'preview', True)
    await vc.reserve_check(1, active, 'file', 'analysis')
    async with ledger() as session, session.begin():
        await session.execute(update(TrialCheck).values(created_at=datetime.now(timezone.utc) - timedelta(hours=2)))
    usage = await vc.user_trial_usage(1)
    # Idle previews expire. Actual work keeps its reservation until settled,
    # even if a process stalls; elapsed time never grants concurrent free work.
    assert usage['used'] == 0 and usage['reserved'] == 1 and usage['remaining'] == 9


@pytest.mark.asyncio
async def test_real_paid_routes_reject_trial_before_handlers(ledger):
    from unittest.mock import AsyncMock
    from src.api import routes, batch_router, designs, reconstruct_router, uploads, bom, groundtruth
    from src.db.engine import get_db_session

    user = AuthedUser(user_id=1, api_key_id=0, key_prefix='session')
    app = FastAPI()
    app.include_router(routes.router, prefix='/api/v1')
    app.include_router(batch_router.router)
    app.include_router(designs.router, prefix='/api/v1/designs')
    app.include_router(reconstruct_router.router)
    app.include_router(uploads.router)
    app.include_router(bom.router, prefix='/api/v1/bom')
    app.include_router(groundtruth.router, prefix='/api/v1/ground-truth')
    app.dependency_overrides[require_api_key] = lambda: user
    app.dependency_overrides[designs.require_design_mutation] = lambda: user
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for path in ('/validate/fit', '/validate/repair', '/validate/assembly?format=analysis',
                     '/validate?segmentation=sam3d', '/batch', '/designs', '/designs/interpret',
                     '/designs/example/revisions', '/reconstruct', '/uploads/multipart',
                     '/uploads/example/parts', '/uploads/example/complete',
                     '/bom/ingest-assembly', '/ground-truth/recalibrate'):
            response = await client.post('/api/v1' + path, files={'file': ('part.stp', b'CAD')})
            assert response.status_code == 403, (path, response.text)
            assert response.json()['detail']['code'] == 'paid_access_required', (path, response.text)
    assert (await vc.user_trial_usage(1))['used'] == 0


@pytest.mark.asyncio
async def test_metering_waits_for_real_result_commit_and_refunds_commit_failure(ledger, monkeypatch):
    from src.db import engine as db
    monkeypatch.setattr(db, "get_session_factory", lambda: ledger)
    app = FastAPI()
    router = APIRouter(route_class=vc.MeteredRoute)

    @router.post('/validate')
    async def compute(request: Request, session=Depends(db.get_db_session),
                      _: None = Depends(vc.enforce_validation_caps)):
        await session.execute(text('INSERT INTO evidence VALUES (:user_id)'),
                              {'user_id': 999 if request.query_params.get('fail_commit') else 1})
        return {'result': 'ready'}

    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=1, api_key_id=0, key_prefix='session')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        response = await asyncio.wait_for(client.post('/validate', files={'file': ('part.stp', b'CAD')}), timeout=5)
        assert response.status_code == 200, response.text
        assert (await vc.user_trial_usage(1))['used'] == 1
        response = await asyncio.wait_for(client.post('/validate?fail_commit=1', files={'file': ('part.stp', b'CAD')}), timeout=5)
        assert response.status_code == 500
        usage = await vc.user_trial_usage(1)
        assert usage['used'] == 1 and usage['reserved'] == 0


@pytest.mark.asyncio
async def test_repair_charges_once_only_after_verified_success(ledger):
    app = FastAPI()
    router = APIRouter(route_class=vc.MeteredRoute)

    @router.post('/validate/repair/verify')
    async def repair(request: Request, _: None = Depends(vc.enforce_validation_caps)):
        if request.query_params.get('success') == 'yes':
            request.state.repair_verified = True
        return {'repair_applied': request.query_params.get('success') == 'yes'}

    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=1, api_key_id=0, key_prefix='session')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        check = str(uuid4())
        async def run(success):
            return await client.post('/validate/repair/verify?success=' + success,
                headers={'x-part-check-id': check}, files={'file': ('open.stl', b'CAD')})
        assert (await run('no')).status_code == 200
        usage = await vc.user_trial_usage(1)
        assert usage['used'] == 0 and usage['reserved'] == 0
        assert (await run('yes')).status_code == 200
        assert (await vc.user_trial_usage(1))['used'] == 1
        assert (await run('yes')).status_code == 409
        with pytest.raises(vc.HTTPException):
            await vc.reserve_check(1, check, 'different', 'analysis')
        existing = str(uuid4())
        await vc.reserve_check(1, existing, 'file', 'analysis')
        await vc.finish_check(1, existing, 'analysis', True)
        with pytest.raises(vc.HTTPException):
            await vc.reserve_check(1, existing, 'file', 'repair')
        for _ in range(8):
            extra = str(uuid4())
            await vc.reserve_check(1, extra, 'file', 'analysis')
            await vc.finish_check(1, extra, 'analysis', True)
        check = str(uuid4())
        assert (await run('yes')).status_code == 403


@pytest.mark.asyncio
async def test_repair_source_conversion_releases_reservation(ledger):
    app = FastAPI()
    router = APIRouter(route_class=vc.MeteredRoute)

    @router.post('/validate/preview-mesh')
    async def convert(request: Request, _: None = Depends(vc.enforce_validation_caps)):
        return {'mesh': 'full source'}

    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=1, api_key_id=0, key_prefix='session')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for _ in range(2):
            response = await client.post('/validate/preview-mesh?purpose=repair',
                headers={'x-part-check-id': str(uuid4())}, files={'file': ('source.step', b'CAD')})
            assert response.status_code == 200
            usage = await vc.user_trial_usage(1)
            assert usage['used'] == 0 and usage['reserved'] == 0 and usage['remaining'] == 10


@pytest.mark.asyncio
async def test_allowance_lock_does_not_block_existing_result_foreign_keys(ledger):
    check = str(uuid4())
    async with ledger() as session, session.begin():
        await session.execute(text('INSERT INTO evidence VALUES (1)'))
        assert await asyncio.wait_for(vc.reserve_check(1, check, 'file', 'analysis'), timeout=5)
        await asyncio.wait_for(vc.finish_check(1, check, 'analysis', True), timeout=5)
    assert (await vc.user_trial_usage(1))['used'] == 1
