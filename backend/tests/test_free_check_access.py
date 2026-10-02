"""The free allowance protects compute, including legacy demo URLs."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import router


def test_anonymous_compute_requires_login():
    app = FastAPI()
    app.include_router(router, prefix='/api/v1')
    with TestClient(app) as client:
        for path in ('/validate', '/validate/cost', '/validate/demo', '/validate/cost/demo', '/validate/repair', '/validate/preview-mesh'):
            response = client.post('/api/v1' + path, files={'file': ('part.stl', b'not CAD')})
            assert response.status_code == 401, (path, response.status_code, response.text)
