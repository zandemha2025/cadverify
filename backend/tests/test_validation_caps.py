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


def _sample_bracket_stl() -> bytes:
    """Python twin of sampleBracketFile() (frontend/src/lib/verify/sample-cad.ts)."""
    outline = [(0, 0), (50, 0), (50, 12), (14, 12), (14, 40), (0, 40)]
    bottom = [(x, y, 0) for x, y in outline]
    top = [(x, y, 6) for x, y in outline]
    triangles = [
        (bottom[0], bottom[2], bottom[1]), (bottom[0], bottom[3], bottom[2]),
        (bottom[0], bottom[5], bottom[3]), (bottom[3], bottom[5], bottom[4]),
        (top[0], top[1], top[2]), (top[0], top[2], top[3]),
        (top[0], top[3], top[5]), (top[3], top[4], top[5]),
    ]
    for i in range(len(outline)):
        n = (i + 1) % len(outline)
        triangles += [(bottom[i], bottom[n], top[n]), (bottom[i], top[n], top[i])]

    def vertex(p):
        return '      vertex ' + ' '.join(str(v) for v in p)

    facets = '\n'.join(
        f'  facet normal 0 0 0\n    outer loop\n{vertex(a)}\n{vertex(b)}\n{vertex(c)}\n    endloop\n  endfacet'
        for a, b, c in triangles
    )
    return f'solid scalecad_routing_bracket\n{facets}\nendsolid scalecad_routing_bracket\n'.encode()


def test_the_sample_hash_is_the_app_sample_bracket():
    import hashlib

    sample = _sample_bracket_stl()
    assert len(sample) == 2463
    assert hashlib.sha256(sample).hexdigest() in vc.SAMPLE_PART_SHA256


@pytest.mark.asyncio
async def test_the_sample_part_never_uses_a_check_and_a_changed_one_counts(ledger):
    app = FastAPI()
    router = APIRouter(route_class=vc.MeteredRoute)
    calls = []

    @router.post('/validate')
    @router.post('/validate/cost')
    @router.post('/validate/preview-mesh')
    async def compute(request: Request, _: None = Depends(vc.enforce_validation_caps)):
        calls.append(getattr(request.state, 'sample_part', False))
        return {'result': 'computed'}

    app.include_router(router)
    await _add_user(ledger, 11, 'trial', 'sampler@gmail.com')  # personal tier: 3
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=11, api_key_id=0, key_prefix='session')
    sample = _sample_bracket_stl()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        async def run(data, name='sample-routing-bracket.stl', check=None):
            for path in ('/validate/preview-mesh', '/validate', '/validate/cost'):
                response = await client.post(path, headers={'x-part-check-id': check or str(uuid4())},
                                             files={'file': (name, data)})
                assert response.status_code == 200, (path, response.text)

        before = await vc.user_trial_usage(11)
        # The whole sample run, repeated, with and without a run id, renamed.
        await run(sample)
        await run(sample)
        await run(sample, name='my-bracket.stl')
        after = await vc.user_trial_usage(11)
        assert (after['used'], after['reserved'], after['remaining']) == (before['used'], before['reserved'], before['remaining']) == (0, 0, 3)
        assert calls == [True] * 9
        async with ledger() as session:
            assert (await session.execute(text('SELECT count(*) FROM trial_checks WHERE user_id = 11'))).scalar_one() == 0
        # One byte changed is an ordinary upload, and counts like one.
        await run(sample + b'\n')
        assert (await vc.user_trial_usage(11))['used'] == 1
        assert calls[-1] is False
        # With the allowance spent, the sample still runs and a new file doesn't.
        await _complete(11, 2)
        assert (await vc.user_trial_usage(11))['remaining'] == 0
        await run(sample)
        denied = await client.post('/validate', headers={'x-part-check-id': str(uuid4())},
                                   files={'file': ('other.stl', sample.replace(b'50 12', b'51 12'))})
        assert denied.status_code == 403
        assert denied.json()['detail']['code'] == 'user_validation_cap_exceeded'


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
async def test_remaining_paid_tools_require_operator_approval_and_stale_previews_expire(ledger):
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
async def test_remaining_paid_routes_reject_trial_before_handlers(ledger):
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
        # ScaleCAD's fixes, mesh repair, Fit in context and Design Studio are
        # on every plan (test_tools_on_every_plan_admit_a_trial_account_without_a_check).
        for path in ('/validate/assembly?format=analysis',
                     '/validate?segmentation=sam3d', '/batch',
                     '/reconstruct', '/uploads/multipart',
                     '/uploads/example/parts', '/uploads/example/complete',
                     '/bom/ingest-assembly', '/ground-truth/recalibrate'):
            response = await client.post('/api/v1' + path, files={'file': ('part.stp', b'CAD')})
            assert response.status_code == 403, (path, response.text)
            assert response.json()['detail']['code'] == 'paid_access_required', (path, response.text)
    assert (await vc.user_trial_usage(1))['used'] == 0


def _fresh_free_limiter(monkeypatch):
    """An enabled, in-memory limiter for the free-account ceilings only."""
    from slowapi import Limiter
    from src.auth import free_tool_limits

    fresh = Limiter(key_func=lambda: "test", storage_uri="memory://", enabled=True)
    monkeypatch.setattr(free_tool_limits, "limiter", fresh)
    return fresh


def _tools_app(monkeypatch, user_id: int):
    """The real routes of the four tools, with only their heavy work stubbed."""
    from unittest.mock import AsyncMock
    from src.api import designs, part_fixes, routes
    from src.db.engine import get_db_session
    from src.services import cad_fix_service, design_service, repair_service
    from tests.test_designs_api import _rows

    user = AuthedUser(user_id=user_id, api_key_id=0, key_prefix='session', role='analyst')
    app = FastAPI()
    app.include_router(routes.router, prefix='/api/v1')
    app.include_router(designs.router, prefix='/api/v1/designs')
    app.include_router(part_fixes.router, prefix='/api/v1/parts')
    app.dependency_overrides[require_api_key] = lambda: user
    app.dependency_overrides[designs.require_design_mutation] = lambda: user
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()

    async def member(user_id):
        return ('01JORGAAAAAAAAAAAAAAAAAAAA', 'member')

    async def fixed(**kwargs):
        return {'applied': True}

    async def repaired(**kwargs):
        return {'repair_applied': True}

    async def generated(*args, **kwargs):
        return _rows()

    monkeypatch.setattr('src.auth.rbac.lookup_org_membership', member)
    monkeypatch.setattr(cad_fix_service, 'apply_fix', fixed)
    monkeypatch.setattr(repair_service, 'repair_mesh', repaired)
    monkeypatch.setattr(design_service, 'create_design', generated)
    monkeypatch.setattr(design_service, 'create_revision', generated)
    monkeypatch.setenv('CONTEXT_FIT_ENABLED', '1')
    monkeypatch.setenv('ADMISSION_DISABLED', '1')
    return app


def _cube_stl() -> bytes:
    import trimesh
    return trimesh.creation.box(extents=[10.0, 10.0, 10.0]).export(file_type='stl')


async def _run_each_tool(client) -> dict[str, int]:
    plan = {'kind': 'plate', 'width_mm': 80.0, 'depth_mm': 50.0, 'thickness_mm': 6.0, 'holes': []}
    cube = _cube_stl()
    responses = {
        'fix': await client.post('/api/v1/parts/' + 'a' * 64 + '/fixes/drain_holes?with_cost=false'),
        'repair': await client.post('/api/v1/validate/repair', files={'file': ('part.stl', cube)}),
        'fit': await client.post('/api/v1/validate/fit', files={'part_a': ('a.stl', cube), 'part_b': ('b.stl', cube)}),
        'design': await client.post('/api/v1/designs', json={'name': 'Plate', 'plan': plan}),
        'revision': await client.post('/api/v1/designs/example/revisions', json={'plan': plan}),
        'interpret': await client.post('/api/v1/designs/interpret', json={'prompt': 'plate 80 x 50 x 6'}),
    }
    return {name: r.status_code for name, r in responses.items()} | {
        name + ':body': r.text for name, r in responses.items() if r.status_code >= 300
    }


@pytest.mark.asyncio
async def test_tools_on_every_plan_admit_a_trial_account_without_a_check(ledger, monkeypatch):
    """User 1 is on the free trial: each tool runs, and none of them uses a check."""
    _fresh_free_limiter(monkeypatch)
    app = _tools_app(monkeypatch, 1)
    before = await vc.user_trial_usage(1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        codes = await _run_each_tool(client)
    assert {k: v for k, v in codes.items() if ':' not in k} == {
        'fix': 200, 'repair': 200, 'fit': 200, 'design': 202, 'revision': 202, 'interpret': 200,
    }, codes
    after = await vc.user_trial_usage(1)
    assert (after['used'], after['reserved'], after['remaining']) == (before['used'], before['reserved'], before['remaining']) == (0, 0, 10)
    async with ledger() as session:
        assert (await session.execute(text('SELECT count(*) FROM trial_checks'))).scalar_one() == 0


@pytest.mark.asyncio
async def test_free_accounts_have_a_per_user_ceiling_on_each_tool(ledger, monkeypatch):
    from src.auth import free_tool_limits as ftl

    _fresh_free_limiter(monkeypatch)
    for env in ('FREE_FIX_LIMIT', 'FREE_REPAIR_LIMIT', 'FREE_FIT_LIMIT', 'FREE_DESIGN_LIMIT'):
        monkeypatch.setenv(env, '2/hour;3/day')
    async with ledger() as session, session.begin():
        await session.execute(text("INSERT INTO users VALUES (4, 'pro', 'pro@acme-aero.com', NULL, NULL)"))
        session.add(BillingAccount(user_id=4, stripe_customer_id='cus_free_tool_test', status='active',
                                   current_period_start=datetime.now(timezone.utc) - timedelta(days=3),
                                   current_period_end=datetime.now(timezone.utc) + timedelta(days=27)))
    trial = AuthedUser(user_id=1, api_key_id=0, key_prefix='session')
    for _ in range(2):
        await ftl.limit_free_fixes(trial)
    with pytest.raises(vc.HTTPException) as limited:
        await ftl.limit_free_fixes(trial)
    assert limited.value.status_code == 429
    detail = limited.value.detail
    assert detail['code'] == 'free_tool_limit' and detail['tool'] == 'fix' and detail['plan'] == 'trial'
    assert detail['message'].startswith('Free accounts can run 2 fixes an hour and 3 a day. You can run the next one in ')
    assert 0 < detail['retry_after_s'] <= 3600
    assert limited.value.headers['Retry-After'] == str(detail['retry_after_s'])
    # Each tool has its own ceiling, and each account its own count.
    await ftl.limit_free_repair(trial)
    await ftl.limit_free_fit(trial)
    await ftl.limit_free_designs(trial)
    await ftl.limit_free_fixes(AuthedUser(user_id=2, api_key_id=0, key_prefix='session'))
    # Another API key of the same account shares the account's count.
    with pytest.raises(vc.HTTPException):
        await ftl.limit_free_fixes(AuthedUser(user_id=1, api_key_id=77, key_prefix='cv_live'))
    # Pilot and active Pro accounts keep only the route limits.
    for paid in (3, 4):
        for _ in range(5):
            await ftl.limit_free_fixes(AuthedUser(user_id=paid, api_key_id=0, key_prefix='session'))
    assert (await vc.user_trial_usage(1))['used'] == 0


@pytest.mark.asyncio
async def test_the_ceiling_is_on_the_real_routes_and_a_limit_is_not_a_check(ledger, monkeypatch):
    _fresh_free_limiter(monkeypatch)
    for env in ('FREE_FIX_LIMIT', 'FREE_REPAIR_LIMIT', 'FREE_FIT_LIMIT', 'FREE_DESIGN_LIMIT'):
        monkeypatch.setenv(env, '1/hour')
    app = _tools_app(monkeypatch, 1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        first = await _run_each_tool(client)
        second = await _run_each_tool(client)
    assert first['fix'] == first['repair'] == first['fit'] == 200 and first['design'] == 202, first
    # One generation an hour covers a design and a revision together.
    assert first['revision'] == 429 and second['design'] == 429, (first, second)
    for tool in ('fix', 'repair', 'fit'):
        assert second[tool] == 429, second
        assert '"code":"free_tool_limit"' in second[tool + ':body'], second
    # Reading a prompt is a local parse: only its route limit applies.
    assert first['interpret'] == second['interpret'] == 200
    assert (await vc.user_trial_usage(1))['used'] == 0
    # The pilot account (user 3) isn't held to the free ceiling.
    app = _tools_app(monkeypatch, 3)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for _ in range(2):
            codes = await _run_each_tool(client)
            assert codes['fix'] == codes['repair'] == codes['fit'] == 200 and codes['design'] == 202, codes


@pytest.mark.asyncio
async def test_free_ceilings_are_off_with_the_rate_limiter_and_never_read_the_plan_then(monkeypatch):
    from slowapi import Limiter
    from src.auth import free_tool_limits as ftl

    monkeypatch.setattr(ftl, 'limiter', Limiter(key_func=lambda: 'x', storage_uri='memory://', enabled=False))

    async def must_not_read(user_id):
        raise AssertionError('read the plan with the limiter off')

    monkeypatch.setattr(vc, 'effective_plan', must_not_read)
    for _ in range(3):
        await ftl.limit_free_fixes(AuthedUser(user_id=1, api_key_id=0, key_prefix='session'))


def test_free_ceiling_wording_and_a_bad_setting_falls_back(monkeypatch):
    from src.auth import free_tool_limits as ftl

    assert ftl.describe('fix') == '10 fixes an hour and 40 a day'
    assert ftl.describe('repair') == '10 mesh repairs an hour and 40 a day'
    assert ftl.describe('fit') == '10 fit measurements an hour and 40 a day'
    assert ftl.describe('design') == '20 designs or revisions an hour and 60 a day'
    assert ftl.describe('catalog') == '6 catalog runs an hour and 20 a day'
    assert ftl.describe('recheck') == '30 re-checks an hour and 150 a day'
    assert ftl.limit_free_catalog_runs in ftl.ALL and ftl.limit_free_recheck in ftl.ALL
    monkeypatch.setenv('FREE_FIX_LIMIT', 'lots')
    assert ftl.describe('fix') == '10 fixes an hour and 40 a day'
    monkeypatch.setenv('FREE_FIX_LIMIT', '1/hour')
    assert ftl.describe('fix') == '1 fix an hour'
    assert [ftl._wait(n) for n in (30, 600, 3597, 3600, 7200)] == [
        'in a minute', 'in 10 minutes', 'in an hour', 'in an hour', 'in 2 hours']


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
