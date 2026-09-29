"""The changed-drawing / unchanged-model journey and unsafe evidence reuse."""
from copy import deepcopy
from datetime import date

import pytest
import pytest_asyncio
from pydantic import ValidationError

from src.services.engineering_package_service import PackageDocument, evaluate_package, review_document


@pytest_asyncio.fixture
async def package_database(monkeypatch):
    import os
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    import src.db.engine as eng
    database = create_async_engine(eng._async_url(os.environ["DATABASE_URL"]), poolclass=NullPool)
    monkeypatch.setattr(eng, "_ENGINE", database)
    monkeypatch.setattr(eng, "_SESSION_FACTORY", async_sessionmaker(database, expire_on_commit=False))
    try:
        yield
    finally:
        await database.dispose()


def package():
    return PackageDocument.model_validate({
        "part_number": "BR214", "revision": "C", "order": "PO40", "quantity": 40,
        "scope": {"process": "cnc_3axis", "material": "6061-T6", "machine": "M07",
                  "setup": "S1", "inspection_method": "CMM"},
        "sources": [{"id": "drawing", "name": "BR214", "kind": "drawing", "revision": "C",
                     "reference": "DMS/BR214/C", "authority": "controlling", "coverage": "complete"},
                    {"id": "study", "name": "Capability and inspection", "kind": "evidence",
                     "reference": "QMS/47", "coverage": "complete"}],
        "requirements": [{"id": "bore", "characteristic": "bore diameter", "feature": "B1",
                          "kind": "dimension", "value": "20", "unit": "mm", "lower": 19.95,
                          "upper": 20.05, "source_id": "drawing", "location": "sheet 1 B4",
                          "required_evidence": ["manufacturing", "inspection"]}],
        "evidence": [{"id": kind, "kind": kind, "source_id": "study", "location": "section 2",
                      "requirement_ids": ["bore"], "conclusion": "supports", "rationale": "Reviewed measured study",
                      "scope": {"process": "cnc_3axis", "material": "6061-T6", "machine": "M07",
                                "setup": "S1", "inspection_method": "CMM"}}
                     for kind in ["manufacturing", "inspection"]],
    })


REPORT = {"status": "OK", "verification": {"verdict": "makeable_in_house", "per_route": {
    "cnc_3axis": {"verdict": "makeable_in_house", "best_machine": "M07", "failures": []}}},
    "estimates": [{"process": "cnc_3axis", "material": "6061-T6", "quantity": 40,
                   "dfm_ready": True, "drivers": [], "unit_cost_usd": 12}]}


def reviewed(doc, previous=None, **requests):
    return review_document(doc, "geometry", previous=previous, user_id=7,
                           source_ids=requests.get("source_ids", [s.id for s in doc.sources]),
                           requirement_ids=requests.get("requirement_ids", [r.id for r in doc.requirements]),
                           evidence_ids=requests.get("evidence_ids", [e.id for e in doc.evidence]),
                           action_ids=[])


def test_changed_drawing_invalidates_only_dependent_evidence_and_keeps_history():
    doc = package()
    receipts = reviewed(doc)
    old = evaluate_package(doc, "geometry", REPORT, receipts, today=date(2026, 9, 29))
    assert old["qualification"] == "reviewed_evidence"
    assert old["authorization"] == "not_recorded"
    revised = doc.model_copy(deep=True)
    revised.revision = "D"
    revised.sources[0].revision = "D"
    revised.requirements[0].lower = 19.99
    revised.requirements[0].upper = 20.01
    inherited = reviewed(revised, receipts, source_ids=[], requirement_ids=[], evidence_ids=[])
    new = evaluate_package(revised, "geometry", REPORT, inherited, previous=doc, today=date(2026, 9, 29))
    assert new["screening"] == "passed"
    assert new["qualification"] == "evidence_needed"
    assert new["changes"]["changed_requirements"] == ["bore"]
    assert {b["kind"] for b in new["blockers"]} >= {"manufacturing", "inspection"}
    assert old["qualification"] == "reviewed_evidence"
    assert doc.revision == "C" and doc.requirements[0].lower == 19.95


def test_changed_setup_expired_evidence_and_failures_cannot_be_reused():
    doc = package()
    receipts = reviewed(doc)
    doc.scope.setup = "S2"
    inherited = reviewed(doc, receipts, source_ids=[], requirement_ids=[], evidence_ids=[])
    assert evaluate_package(doc, "geometry", REPORT, inherited)["qualification"] == "evidence_needed"
    doc = package()
    doc.evidence[0].expires_on = date(2026, 1, 1)
    doc.evidence[1].conclusion = "fails"
    result = evaluate_package(doc, "geometry", REPORT, reviewed(doc), today=date(2026, 9, 29))
    assert result["qualification"] == "evidence_needed"
    assert any(e["reason"] == "expired" for e in result["evidence_status"])


def test_conflicting_sources_and_dangling_links_cannot_pass():
    doc = package()
    other = doc.requirements[0].model_copy(update={"id": "model-bore", "upper": 20.2})
    doc.requirements.append(other)
    result = evaluate_package(doc, "geometry", REPORT, reviewed(doc))
    assert any(b["kind"] == "conflict" for b in result["blockers"])
    invalid = package().model_dump()
    invalid["requirements"][0]["source_id"] = "missing"
    with pytest.raises(ValidationError):
        PackageDocument.model_validate(invalid)


def test_unreviewed_or_empty_package_never_becomes_qualified():
    doc = package()
    assert evaluate_package(doc, "geometry", REPORT, {})["qualification"] == "evidence_needed"
    doc.requirements = []
    doc.evidence = []
    assert evaluate_package(doc, "geometry", REPORT, reviewed(doc))["qualification"] == "evidence_needed"


def test_failure_disposition_requires_review_and_retains_observation():
    from src.services.engineering_package_service import Outcome
    doc = package()
    doc.outcomes = [Outcome(id="failed-run", source_id="study", location="run 1", revision="C",
        order="PO40", scope=doc.scope, requirement_ids=["bore"], samples=10, failures=2,
        observed_on=date(2026, 9, 28), note="Two bores above the upper limit")]
    assert any(b["kind"] == "outcome" for b in evaluate_package(doc, "geometry", REPORT, reviewed(doc))["blockers"])
    doc.evidence[0].outcome_ids = ["failed-run"]
    doc.evidence[0].conclusion = "fails"
    replacement = doc.evidence[0].model_copy(deep=True)
    replacement.id = "corrected-study"
    replacement.outcome_ids = []
    replacement.conclusion = "supports"
    replacement.rationale = "Reviewed corrective action and new capability study at QMS/47 section 3"
    replacement.location = "section 3"
    replacement.supersedes_evidence_ids = ["manufacturing"]
    doc.evidence.append(replacement)
    result = evaluate_package(doc, "geometry", REPORT, reviewed(doc, evidence_ids=["manufacturing", "inspection"]))
    assert result["qualification"] == "evidence_needed"
    result = evaluate_package(doc, "geometry", REPORT, reviewed(doc))
    assert result["qualification"] == "reviewed_evidence"
    assert doc.outcomes[0].failures == 2 and len(doc.evidence) == 3
    assert result["evidence_status"][0]["status"] == "superseded"


def test_owned_action_closure_and_external_authorization_have_distinct_reviews():
    from src.services.engineering_package_service import Action, Authorization, Evidence
    doc = package()
    doc.actions = [Action(id="a", blocker_id="manufacturing:bore", title="Confirm process capability",
        owner="Manufacturing engineering", required_evidence="Measured capability study",
        requirement_ids=["bore"], closure_evidence_ids=["manufacturing"], rationale="Capability reviewed")]
    initial = evaluate_package(doc, "geometry", REPORT, {})
    assert next(b for b in initial["blockers"] if b["id"] == "manufacturing:bore")["owner"] == "Manufacturing engineering"
    receipts = reviewed(doc)
    awaiting_closure = evaluate_package(doc, "geometry", REPORT, receipts)
    assert awaiting_closure["action_status"][0]["status"] == "open"
    assert awaiting_closure["qualification"] == "evidence_needed"
    receipts = review_document(doc, "geometry", previous=receipts, user_id=8,
        source_ids=[], requirement_ids=[], evidence_ids=[], action_ids=["a"])
    closed = evaluate_package(doc, "geometry", REPORT, receipts)
    assert closed["action_status"][0]["status"] == "closed"
    assert closed["qualification"] == "reviewed_evidence"
    doc.evidence.append(Evidence(id="release", kind="authorization", source_id="study", location="customer release 47",
        scope=doc.scope, conclusion="supports", rationale="Customer authorization for PO40 only"))
    doc.authorization = Authorization(authority="Customer engineering", reference="release 47", activity="PO40 only",
        revision="C", order="PO40", evidence_id="release")
    authorized = evaluate_package(doc, "geometry", REPORT, reviewed(doc))
    assert authorized["authorization"] == "external_record_attached"
    doc.order = "PO41"
    assert evaluate_package(doc, "geometry", REPORT, reviewed(doc))["authorization"] == "not_recorded"


@pytest.mark.asyncio
async def test_changed_manufacturing_inputs_invalidate_current_assessment(monkeypatch):
    from dataclasses import asdict, replace
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from src.costing.makeability import MachineCap
    from src.services import engineering_package_service as svc, machine_inventory_service as machines, part_context_service as contexts
    machine = MachineCap(name="M07", process="cnc_3axis", capabilities={"x": 100, "y": 100, "z": 100})
    machine_loader = AsyncMock(return_value=[machine])
    context_loader = AsyncMock(return_value=None)
    monkeypatch.setattr(machines, "load_org_inventory", machine_loader)
    monkeypatch.setattr(machines, "load_shop_caps", AsyncMock(return_value=None))
    monkeypatch.setattr(contexts, "get_context", context_loader)
    doc = package()
    report = deepcopy(REPORT)
    report["evaluation_context"] = {"inventory": [asdict(machine)]}
    initial = await svc.current_report(None, "org", "mesh", report, doc.scope)
    assert not initial["evaluation_stale"]
    receipts = svc.review_document(doc, "mesh", previous=None, user_id=7,
        source_ids=[s.id for s in doc.sources], requirement_ids=["bore"],
        evidence_ids=[e.id for e in doc.evidence], action_ids=[], evaluation_context=initial["review_context"])
    assert evaluate_package(doc, "mesh", initial, receipts)["qualification"] == "reviewed_evidence"
    machine_loader.return_value = [replace(machine, capabilities={"x": 5, "y": 5, "z": 5})]
    changed = await svc.current_report(None, "org", "mesh", report, doc.scope)
    assessment = evaluate_package(doc, "mesh", changed, receipts)
    assert changed["evaluation_stale"] and assessment["screening"] == "unknown"
    assert all(e["reason"] == "review_required" for e in assessment["evidence_status"])
    machine_loader.return_value = [machine]
    context_loader.return_value = SimpleNamespace(service_environment={"max_temp_c": 900})
    assert (await svc.current_report(None, "org", "mesh", report, doc.scope))["evaluation_stale"]
    assert (await svc.current_report(None, "org", "mesh", REPORT, doc.scope))["evaluation_stale"]


def test_import_and_packet_preserve_sources_without_executing_content():
    from types import SimpleNamespace
    from src.services.engineering_package_service import import_characteristics, export_characteristics, packet_html
    doc = package()
    doc.requirements[0].value = "=HYPERLINK(\"https://example.com\")"
    doc.note = '<script>alert("x")</script>'
    payload = {"document": doc.model_dump(mode="json"), "evaluation": evaluate_package(doc, "geometry", REPORT, {}),
               "reviews": {}, "evaluated_on": "2026-09-29", "review_note": "Test"}
    csv = export_characteristics(payload)
    assert "'=HYPERLINK" in csv
    imported = import_characteristics(csv.encode(), "characteristics.csv")
    assert imported[0]["source_id"] == "drawing"
    html = packet_html(SimpleNamespace(payload=payload, version=1, state="draft", id="p", mesh_hash="geometry"))
    assert "<script>" not in html and "&lt;script&gt;" in html


@pytest.mark.skipif(not __import__("os").environ.get("DATABASE_URL", "").startswith("postgresql"), reason="requires live Postgres")
@pytest.mark.asyncio
async def test_package_http_versions_files_exports_conflicts_and_tenant_isolation(monkeypatch, tmp_path, package_database):
    import asyncio
    import uuid
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from sqlalchemy import select, text
    from ulid import ULID
    from src.api.engineering_packages import router
    from src.api.catalog import router as catalog_router
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    import src.db.engine as eng
    from src.db.models import CostDecision

    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("ENGINEERING_DOCUMENT_BLOB_DIR", str(tmp_path))
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/packages")
    app.include_router(catalog_router, prefix="/catalog")
    identities = []
    tag = uuid.uuid4().hex
    async with eng.get_session_factory()() as session:
        for i in range(2):
            org = str(ULID())
            email = f"ep-{tag}-{i}@example.test"
            await session.execute(text("INSERT INTO organizations (id,name,slug) VALUES (:id,:id,:slug)"), {"id": org, "slug": f"ep-{tag}-{i}"})
            uid = (await session.execute(text("INSERT INTO users (email,email_lower,role,auth_provider,current_org_id) VALUES (:email,:email,'analyst','password',:org) RETURNING id"), {"email": email, "org": org})).scalar_one()
            await session.execute(text("INSERT INTO memberships (id,org_id,user_id,org_role) VALUES (:id,:org,:uid,'admin')"), {"id": str(ULID()), "org": org, "uid": uid})
            identities.append((org, uid))
        decision_id = str(ULID())
        from src.services.machine_inventory_service import create_machine, load_org_inventory
        from src.services.cost_decision_service import evaluation_context
        from src.costing.estimate import EstimateOptions
        await create_machine(session, identities[0][0], {"name": "M07", "process": "cnc_3axis", "count": 1,
            "max_workpiece_kg": 100, "capabilities": {"x": 100, "y": 100, "z": 100}, "materials": ["aluminum"]}, created_by=identities[0][1])
        report = deepcopy(REPORT)
        report["evaluation_context"] = evaluation_context(EstimateOptions(inventory=tuple(await load_org_inventory(session, identities[0][0]))))
        session.add(CostDecision(ulid=decision_id, user_id=identities[0][1], org_id=identities[0][0],
            mesh_hash="a" * 64, params_hash=tag, engine_version="test", filename="bracket.step", file_type="step", result_json=report))
        await session.commit()

    def act(index=0, role="analyst"):
        org, uid = identities[index]
        app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=uid, api_key_id=0, key_prefix="test", role=role, org_id=org)
    act()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        part = await client.get("/catalog/parts/" + "a" * 64)
        assert part.status_code == 200 and part.json()["part_key"] == "a" * 64
        assert (await client.get("/catalog/parts/not-a-hash")).status_code == 404
        upload = await client.post("/packages/documents", files={"file": ("study.txt", b"Measured study", "text/plain")})
        assert upload.status_code == 200, upload.text
        doc = package().model_dump(mode="json")
        doc["evidence"][0]["expires_on"] = date.today().isoformat()
        doc["sources"][1].update({"sha256": upload.json()["sha256"], "filename": "study.txt"})
        body = {"decision_id": decision_id, "document": doc, "confirm_sources": ["drawing", "study"],
                "confirm_requirements": ["bore"], "review_evidence": ["manufacturing", "inspection"],
                "state": "issued", "review_note": "Reviewed evidence, no release authority"}
        first = await client.post("/packages", json=body)
        assert first.status_code == 201, first.text
        old = first.json()
        assert old["qualification"] == "reviewed_evidence"
        assert (await client.get(f"/packages/{old['id']}")).json()["current_assessment"]["qualification"] == "reviewed_evidence"
        # Reusing an older result cannot clear staleness on the newer catalog projection.
        from src.services.cost_decision_service import _refresh_summary_for
        async with eng.get_session_factory()() as session:
            prior = (await session.execute(select(CostDecision).where(CostDecision.ulid == decision_id))).scalar_one()
            newer = CostDecision(ulid=str(ULID()), user_id=identities[0][1], org_id=identities[0][0],
                mesh_hash="a" * 64, params_hash=tag + "new", engine_version="test", filename="bracket.step",
                file_type="step", result_json=report)
            session.add(newer)
            await session.flush()
            await _refresh_summary_for(session, newer)
            await session.execute(text("UPDATE part_summaries SET makeability_stale = true WHERE org_id = :org"), {"org": identities[0][0]})
            await _refresh_summary_for(session, prior)
            stale = (await session.execute(text("SELECT makeability_stale FROM part_summaries WHERE org_id = :org"), {"org": identities[0][0]})).scalar_one()
            assert stale is True
            await session.commit()
        assert (await client.get(f"/packages/{old['id']}/documents/study")).content == b"Measured study"
        for format in ["json", "csv", "html", "pdf"]:
            export = await client.get(f"/packages/{old['id']}/export.{format}")
            assert export.status_code == 200, export.text[:100]
            if format == "pdf":
                assert export.content.startswith(b"%PDF")
        revised = deepcopy(body)
        revised.update(previous_id=old["id"], state="draft", confirm_sources=[], confirm_requirements=[], review_evidence=[])
        revised["document"]["revision"] = "D"
        revised["document"]["requirements"][0]["upper"] = 20.01
        # Two simultaneous saves cannot overwrite one another or create two heads.
        saves = await asyncio.gather(client.post("/packages", json=revised), client.post("/packages", json=revised))
        assert sorted(r.status_code for r in saves) == [201, 409], [r.text for r in saves]
        latest = next(r.json() for r in saves if r.status_code == 201)
        assert latest["qualification"] == "evidence_needed"
        history = (await client.get("/packages", params={"series_id": old["series_id"], "limit": 1})).json()
        assert history["packages"][0]["version"] == 2 and history["next_cursor"]
        older = (await client.get(f"/packages/{old['id']}")).json()
        assert older["document"]["revision"] == "C" and older["evaluation"] == old["evaluation"]
        latest_read = (await client.get(f"/packages/{latest['id']}")).json()
        assert latest_read["current_assessment"]["changes"]["changed_requirements"] == ["bore"]
        queue = await client.get("/packages/queue")
        assert queue.status_code == 200 and queue.json()["groups"]
        from datetime import timedelta
        from src.services import engineering_package_service as svc
        today = date.today()
        class NextDay(date):
            @classmethod
            def today(cls):
                return today + timedelta(days=1)
        with monkeypatch.context() as clock:
            clock.setattr(svc, "date", NextDay)
            expired = (await client.get(f"/packages/{old['id']}")).json()
            assert expired["qualification"] == "reviewed_evidence"
            assert expired["current_assessment"]["qualification"] == "evidence_needed"
            assert expired["current_assessment"]["evidence_status"][0]["reason"] == "expired"
        act(0, "viewer")
        assert (await client.post("/packages", json=revised)).status_code == 403
        act(1)
        assert (await client.get("/catalog/parts/" + "a" * 64)).status_code == 404
        assert (await client.get(f"/packages/{old['id']}")).status_code == 404
        assert (await client.get(f"/packages/{old['id']}/documents/study")).status_code == 404
        assert (await client.get("/packages")).json()["packages"] == []
        assert (await client.post("/packages", json=body)).status_code == 404
