"""Browser repair is untrusted; the server verifies bytes before charging."""
import hashlib
import importlib
import io
from pathlib import Path

import trimesh
from fastapi.testclient import TestClient


def test_local_repair_verification_is_based_on_actual_geometry():
    import main
    importlib.reload(main)
    with TestClient(main.app) as client:
        mesh = trimesh.creation.box(extents=[10, 20, 30])
        solid = mesh.export(file_type='stl')
        good = client.post('/api/v1/validate/repair/verify', files={'file': ('repaired.stl', solid)}).json()
        assert good['verified'] is True
        assert good['sha256'] == hashlib.sha256(solid).hexdigest()
        mesh.update_faces(list(range(1, len(mesh.faces))))
        bad = client.post('/api/v1/validate/repair/verify', files={'file': ('still-open.stl', mesh.export(file_type='stl'))}, data={'verified': 'true'}).json()
        assert bad['verified'] is False
        assert any(i['code'] == 'NON_WATERTIGHT' for i in bad['analysis']['universal_issues'])


def test_repair_source_exports_the_full_mesh():
    import main
    importlib.reload(main)
    data = (Path(__file__).parent / 'assets' / 'cube.step').read_bytes()
    with TestClient(main.app) as client:
        response = client.post('/api/v1/validate/preview-mesh?purpose=repair', files={'file': ('cube.step', data)})
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'model/stl'
    mesh = trimesh.load(io.BytesIO(response.content), file_type='stl')
    from src.api.routes import _parse_mesh
    source, _ = _parse_mesh(data, 'cube.step')
    assert len(mesh.faces) == len(source.faces)
    assert mesh.is_volume and abs(mesh.volume - source.volume) < 0.001
