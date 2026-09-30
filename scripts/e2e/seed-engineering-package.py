"""Seed synthetic browser QA data into an explicitly configured local test stack."""
import asyncio,json,os,sys
from urllib.parse import urlsplit
from pathlib import Path
if urlsplit(os.environ.get('DATABASE_URL', '')).hostname not in {'localhost', '127.0.0.1', '::1'}:
 raise SystemExit('Set DATABASE_URL to an isolated local test database, never production.')
if not os.environ.get('DASHBOARD_SESSION_SECRET'):
 raise SystemExit('Use the same DASHBOARD_SESSION_SECRET as the local test backend.')
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'backend'))
from sqlalchemy import text
from ulid import ULID
from src.db.engine import get_session_factory
from src.auth.dashboard_session import sign
from src.auth.require_api_key import AuthedUser
from src.services.cost_decision_service import persist_cost_decision,evaluation_context
from src.services.source_artifact_service import save_source_artifact
from src.services.machine_inventory_service import create_machine
from tests.test_phase_c_makeability_wire import _mill
from tests.test_costing_model import _analyze,_bulky_block
from src.costing import EstimateOptions,estimate_decision,report_to_dict
from src.services.analysis_service import compute_mesh_hash
async def main():
 org=str(ULID()); email='engineering-browser-'+org.lower()+'@example.test'
 async with get_session_factory()() as s:
  await s.execute(text('INSERT INTO organizations (id,name,slug) VALUES (:o,:o,:o)'),{'o':org})
  uid=(await s.execute(text("INSERT INTO users (email,email_lower,role,auth_provider,current_org_id,plan) VALUES (:e,:e,'analyst','password',:o,'pilot') RETURNING id"),{'e':email,'o':org})).scalar_one()
  await s.execute(text("INSERT INTO memberships(id,org_id,user_id,org_role) VALUES (:i,:o,:u,'admin')"),{'i':str(ULID()),'o':org,'u':uid})
  machine=_mill(name='M07')
  await create_machine(s,org,{'name':'M07','process':'cnc_3axis','count':1,'max_workpiece_kg':200,'hourly_rate_usd':75,'capital_frac':.4,'capabilities':machine.capabilities,'materials':['steel','Mild Steel']},created_by=uid)
  result,mesh,features=_analyze(_bulky_block())
  data=mesh.export(file_type='stl'); sha=compute_mesh_hash(data)
  options=EstimateOptions(quantities=[40],material_class='steel',material_class_is_user=True,inventory=(machine,))
  report=report_to_dict(estimate_decision(result,mesh,features,options)); report['evaluation_context']=evaluation_context(options)
  decision=await persist_cost_decision(s,AuthedUser(user_id=uid,api_key_id=0,key_prefix='session'),mesh_hash=sha,params_hash=org,engine_version='local-e2e',filename='BR214-browser.stl',file_type='stl',result_json=report)
  await save_source_artifact(org,sha,'.stl',data)
  await s.commit()
  target=Path(os.environ.get('E2E_SESSION_FILE', '/tmp/cadverify-engineering-browser.json')); target.touch(mode=0o600, exist_ok=True); target.chmod(0o600); target.write_text(json.dumps({'cookie':sign(uid),'user_id':uid,'decision_id':decision.ulid,'mesh_hash':sha,'report':report})); target.chmod(0o600)
  print('Local browser fixture created with a real computed manufacturing report.')
asyncio.run(main())
