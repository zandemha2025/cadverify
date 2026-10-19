"""Real PostgreSQL checks for check allowances, races and refunds.

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
from src.db.models import BillingAccount, TrialCheck


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
            await connection.execute(text(
                'CREATE TABLE users (id bigint PRIMARY KEY, plan text NOT NULL, email_lower text, '
                'free_check_grant integer, phone_verified_at timestamptz)'
            ))
            await connection.execute(text('CREATE TABLE evidence (user_id bigint REFERENCES users(id) DEFERRABLE INITIALLY DEFERRED)'))
            await connection.run_sync(TrialCheck.__table__.create)
            await connection.run_sync(BillingAccount.__table__.create)
            # Users 1-3 predate email tiers and keep the grandfathered 10-check grant.
            await connection.execute(text(
                "INSERT INTO users VALUES (1, 'trial', 'one@gmail.com', 10, NULL), "
                "(2, 'trial', 'two@acme-aero.com', 10, NULL), (3, 'pilot', 'ops@acme-aero.com', NULL, NULL)"
            ))
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
    # Eight completed parts plus one in-flight part leaves exactly one slot,
    # even when sixteen different files arrive concurrently on separate connections.
    for i in range(8):
        check = str(uuid4())
        assert await vc.reserve_check(1, check, f'file-{i}', 'analysis')
        await vc.finish_check(1, check, 'analysis', True)
    pending = str(uuid4())
    await vc.reserve_check(1, pending, 'file-pending', 'analysis')
    ids = [str(uuid4()) for _ in range(16)]
    results = await asyncio.gather(*(vc.reserve_check(1, check, f'race-{n}', 'analysis') for n, check in enumerate(ids)), return_exceptions=True)
    admitted = [result for result in results if not isinstance(result, BaseException)]
    assert admitted == [ids[results.index(admitted[0])]]
    winner = f'race-{results.index(admitted[0])}'
    rejected = [result for result in results if isinstance(result, BaseException)]
    assert all(isinstance(result, vc.HTTPException) and result.status_code == 403 for result in rejected)
    assert (await vc.user_trial_usage(1))['remaining'] == 0
    # The tenth part finishes its own cost and preview. A step that is still
    # running can't start twice; a finished step re-runs as a new run of the
    # same part and never takes an eleventh check. Changing the file is denied.
    last = admitted[0]
    await vc.finish_check(1, last, 'analysis', True)
    for op in ('cost', 'preview'):
        await vc.reserve_check(1, last, winner, op)
        with pytest.raises(vc.HTTPException) as running:
            await vc.reserve_check(1, last, winner, op)
        assert running.value.status_code == 409
        assert running.value.detail['code'] == 'check_operation_exists'
        await vc.finish_check(1, last, op, True)
        rerun = await vc.reserve_check(1, last, winner, op)
        assert rerun and rerun != last
        await vc.finish_check(1, rerun, op, True)
    with pytest.raises(vc.HTTPException) as changed:
        await vc.reserve_check(1, last, 'different', 'preview-analysis')
    assert changed.value.detail['code'] == 'check_file_mismatch'
    usage = await vc.user_trial_usage(1)
    assert (usage['used'], usage['reserved'], usage['remaining']) == (9, 1, 0)
    await vc.finish_check(1, pending, 'analysis', False)
    assert (await vc.user_trial_usage(1))['remaining'] == 1
    await vc.reserve_check(1, pending, 'file-pending', 'analysis')
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
        await vc.reserve_check(1, str(uuid4()), 'a-new-file', 'analysis')
    # A part checked 90 days ago re-runs any step without another check, even
    # with the allowance spent.
    for op in ('analysis', 'cost', 'preview-analysis'):
        again = await vc.reserve_check(1, str(uuid4()), 'file-3', op)
        await vc.finish_check(1, again, op, True)
    assert (await vc.user_trial_usage(1))['used'] == 10


@pytest.mark.asyncio
async def test_a_check_means_a_part(ledger):
    """Same file any number of times = 1 check; different files count; the cap holds for new files."""
    await _add_user(ledger, 9, 'trial', 'new@gmail.com')  # personal tier: 3
    # The first run of a part: preview, analysis and cost share one check id.
    first = str(uuid4())
    for op in ('preview-analysis', 'analysis', 'cost'):
        assert await vc.reserve_check(9, first, 'bracket', op) == first
        await vc.finish_check(9, first, op, True)
    assert (await vc.user_trial_usage(9))['used'] == 1
    # Re-cost in another material, re-check after adding machines, change the
    # quantities: same file, new browser run ids, or no id at all.
    for check_id in (first, str(uuid4()), None, str(uuid4())):
        for op in ('cost', 'analysis'):
            run = await vc.reserve_check(9, check_id, 'bracket', op)
            await vc.finish_check(9, run, op, True)
    assert (await vc.user_trial_usage(9))['used'] == 1
    # A different file is its own check.
    other = await vc.reserve_check(9, str(uuid4()), 'housing', 'analysis')
    await vc.finish_check(9, other, 'analysis', True)
    usage = await vc.user_trial_usage(9)
    assert (usage['used'], usage['remaining']) == (2, 1)
    # Sixteen simultaneous runs of one NEW file take only the last slot.
    runs = await asyncio.gather(*(vc.reserve_check(9, str(uuid4()), 'plate', 'analysis') for _ in range(16)))
    assert len(set(runs)) == 16
    usage = await vc.user_trial_usage(9)
    assert (usage['used'], usage['reserved'], usage['remaining']) == (2, 1, 0)
    # The cap still holds for a file the account hasn't checked...
    with pytest.raises(vc.HTTPException) as exhausted:
        await vc.reserve_check(9, str(uuid4()), 'bracket-rev-b', 'analysis')
    assert exhausted.value.detail['code'] == 'user_validation_cap_exceeded'
    # ...and the plate keeps its slot while any of its runs finishes.
    for n, run in enumerate(runs):
        await vc.finish_check(9, run, 'analysis', n == 5)
    usage = await vc.user_trial_usage(9)
    assert (usage['used'], usage['reserved'], usage['remaining']) == (3, 0, 0)
    # A run that failed releases nothing it didn't take: the file is still checked.
    again = await vc.reserve_check(9, str(uuid4()), 'housing', 'cost')
    await vc.finish_check(9, again, 'cost', False)
    assert (await vc.user_trial_usage(9))['used'] == 3


@pytest.mark.asyncio
async def test_a_failed_only_run_of_a_new_file_releases_its_slot(ledger):
    await _add_user(ledger, 10, 'trial', 'solo@gmail.com')
    await _complete(10, 2)
    attempts = [await vc.reserve_check(10, str(uuid4()), 'bad-file', 'analysis') for _ in range(3)]
    assert (await vc.user_trial_usage(10))['remaining'] == 0
    for run in attempts:
        await vc.finish_check(10, run, 'analysis', False)
    usage = await vc.user_trial_usage(10)
    assert (usage['used'], usage['reserved'], usage['remaining']) == (2, 0, 1)


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
        # Re-running a finished step on the same file runs again, same check.
        assert (await post('/validate', check)).status_code == 200
        assert (await post('/validate/cost', str(uuid4()))).status_code == 200
        assert (await vc.user_trial_usage(1))['used'] == 1
        assert (await post('/validate', str(uuid4()), b'')).status_code == 400
        assert (await post('/validate', 'not-a-uuid')).status_code == 400
        assert len(calls) == 6
        # A real DB query failure blocks compute rather than spending unchecked.
        async def unavailable(*args):
            raise vc.SQLAlchemyError('database unavailable')
        monkeypatch.setattr(vc, '_counts', unavailable)
        assert (await post('/validate', str(uuid4()), b'NEW CAD')).status_code == 503
        assert len(calls) == 6


@pytest.mark.asyncio
async def test_headerless_api_calls_count_one_check_per_part(ledger):
    # API clients that never send x-part-check-id: analysis and cost of the
    # same file are one part check, not two.
    app = FastAPI()
    router = APIRouter(route_class=vc.MeteredRoute)

    @router.post('/validate')
    @router.post('/validate/cost')
    @router.post('/validate/preview-mesh')
    async def compute(_: None = Depends(vc.enforce_validation_caps)):
        return {'result': 'computed'}

    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=1, api_key_id=7, key_prefix='cv_live')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        async def post(path, data):
            return await client.post(path, files={'file': ('part.stp', data)})
        for path in ('/validate/preview-mesh', '/validate', '/validate/cost'):
            assert (await post(path, b'PART A')).status_code == 200
        assert (await vc.user_trial_usage(1))['used'] == 1
        # Re-running a finished step is the same part's check; another file is its own.
        assert (await post('/validate', b'PART A')).status_code == 200
        assert (await post('/validate', b'PART B')).status_code == 200
        assert (await post('/validate/cost', b'PART B')).status_code == 200
        assert (await vc.user_trial_usage(1))['used'] == 2
        # Hours later the same file still doesn't count again.
        async with ledger() as session, session.begin():
            await session.execute(update(TrialCheck).values(created_at=datetime.now(timezone.utc) - timedelta(hours=2)))
        assert (await post('/validate/cost', b'PART A')).status_code == 200
        assert (await post('/validate', b'PART A')).status_code == 200
        assert (await vc.user_trial_usage(1))['used'] == 2


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
async def test_allowance_lock_does_not_block_existing_result_foreign_keys(ledger):
    check = str(uuid4())
    async with ledger() as session, session.begin():
        await session.execute(text('INSERT INTO evidence VALUES (1)'))
        assert await asyncio.wait_for(vc.reserve_check(1, check, 'file', 'analysis'), timeout=5)
        await asyncio.wait_for(vc.finish_check(1, check, 'analysis', True), timeout=5)
    assert (await vc.user_trial_usage(1))['used'] == 1


async def _add_user(ledger, user_id, plan, email, grant=None):
    async with ledger() as session, session.begin():
        await session.execute(text('INSERT INTO users VALUES (:id, :plan, :email, :grant, NULL)'),
                              {'id': user_id, 'plan': plan, 'email': email, 'grant': grant})


async def _complete(user_id, count, prefix='file'):
    """``count`` checks of distinct files (a check means a part)."""
    for _ in range(count):
        check = str(uuid4())
        assert await vc.reserve_check(user_id, check, f'{prefix}-{uuid4().hex}', 'analysis')
        await vc.finish_check(user_id, check, 'analysis', True)


@pytest.mark.asyncio
async def test_email_tiers_size_new_accounts_and_keep_grandfathered_grants(ledger, monkeypatch):
    await _add_user(ledger, 4, 'trial', 'new@gmail.com')
    await _add_user(ledger, 5, 'trial', 'eng@acme-aero.com')
    await _add_user(ledger, 6, 'trial', 'old@yahoo.com', grant=10)
    personal, work, legacy = [await vc.user_trial_usage(u) for u in (4, 5, 6)]
    assert (personal['cap'], personal['tier']) == (3, 'personal')
    assert (work['cap'], work['tier']) == (15, 'work')
    assert (legacy['cap'], legacy['tier']) == (10, 'personal')
    # A grandfathered work account gets the larger work tier.
    assert (await vc.user_trial_usage(2))['cap'] == 15

    await _complete(4, 3)
    with pytest.raises(vc.HTTPException) as exhausted:
        await vc.reserve_check(4, str(uuid4()), 'file', 'analysis')
    detail = exhausted.value.detail
    assert exhausted.value.status_code == 403
    assert detail['code'] == 'user_validation_cap_exceeded'
    assert (detail['cap'], detail['tier'], detail['plan']) == (3, 'personal', 'trial')
    assert 'Your 3 free checks' in detail['message'] and 'lifetime' not in detail['message']

    # Operators tune both tiers without a deploy of new code.
    monkeypatch.setenv('FREE_CHECKS_PERSONAL', '5')
    monkeypatch.setenv('FREE_CHECKS_WORK', '20')
    assert (await vc.user_trial_usage(4))['remaining'] == 2
    assert (await vc.user_trial_usage(5))['cap'] == 20
    assert (await vc.user_trial_usage(6))['cap'] == 10


@pytest.mark.asyncio
async def test_pro_counts_only_the_current_billing_period_and_lapses_to_free(ledger, monkeypatch):
    monkeypatch.setenv('PRO_MONTHLY_CHECKS', '4')
    now = datetime.now(timezone.utc)
    await _add_user(ledger, 7, 'trial', 'buyer@acme-aero.com')
    await _complete(7, 15)  # the whole free tier, used before upgrading
    async with ledger() as session, session.begin():
        await session.execute(update(TrialCheck).where(TrialCheck.user_id == 7).values(created_at=now - timedelta(days=3)))
        await session.execute(text("UPDATE users SET plan = 'pro' WHERE id = 7"))
        session.add(BillingAccount(user_id=7, stripe_customer_id='cus_test7', stripe_subscription_id='sub_test7',
                                   status='active', current_period_start=now - timedelta(days=1),
                                   current_period_end=now + timedelta(days=29)))
    usage = await vc.user_trial_usage(7)
    assert (usage['plan'], usage['cap'], usage['used'], usage['remaining']) == ('pro', 4, 0, 4)
    assert usage['resets_at'] is not None
    await _complete(7, 4)
    with pytest.raises(vc.HTTPException) as exhausted:
        await vc.reserve_check(7, str(uuid4()), 'file', 'analysis')
    assert exhausted.value.detail['plan'] == 'pro'
    assert "this month's 4 Pro checks" in exhausted.value.detail['message']
    # Past due keeps access while Stripe retries the card.
    async with ledger() as session, session.begin():
        await session.execute(update(BillingAccount).where(BillingAccount.user_id == 7).values(status='past_due'))
    assert (await vc.user_trial_usage(7))['plan'] == 'pro'
    # A cancelled subscription falls back to the free allowance, already spent.
    async with ledger() as session, session.begin():
        await session.execute(update(BillingAccount).where(BillingAccount.user_id == 7).values(status='canceled'))
    lapsed = await vc.user_trial_usage(7)
    assert (lapsed['plan'], lapsed['cap'], lapsed['used'], lapsed['remaining']) == ('trial', 15, 19, 0)


@pytest.mark.asyncio
async def test_phone_gate_holds_free_checks_until_verified(ledger, monkeypatch):
    await _add_user(ledger, 8, 'trial', 'new@acme-aero.com')
    assert await vc.reserve_check(8, str(uuid4()), 'file', 'analysis')  # off by default
    monkeypatch.setenv('SMS_VERIFICATION_REQUIRED', '1')
    assert (await vc.user_trial_usage(8))['phone_verification_required'] is True
    with pytest.raises(vc.HTTPException) as gated:
        await vc.reserve_check(8, str(uuid4()), 'file-2', 'analysis')
    assert gated.value.detail['code'] == 'phone_verification_required'
    # The part admitted before the gate can still run its other steps: no new check.
    assert await vc.reserve_check(8, str(uuid4()), 'file', 'cost')
    # Pilot accounts are never gated.
    assert not await vc.reserve_check(3, str(uuid4()), 'file', 'analysis')
    async with ledger() as session, session.begin():
        await session.execute(text('UPDATE users SET phone_verified_at = now() WHERE id = 8'))
    assert (await vc.user_trial_usage(8))['phone_verification_required'] is False
    assert await vc.reserve_check(8, str(uuid4()), 'file-2', 'analysis')
