# Testing Patterns

**Analysis Date:** 2026-04-15

## Test Framework

**Runner:**
- pytest (Python backend only)
- No frontend tests configured
- Config: `backend/pyproject.toml` with pytest options
  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  pythonpath = ["."]
  addopts = "-ra --strict-markers"
  filterwarnings = [
      "ignore::DeprecationWarning",
      "ignore::PendingDeprecationWarning",
  ]
  ```

**Assertion Library:**
- pytest assertions (no external library needed)

**Run Commands:**
```bash
pytest tests/                    # Run all tests
pytest tests/ -v                # Verbose output
pytest tests/test_api.py         # Run specific file
pytest -k test_name              # Run by test name pattern
```

## Test File Organization

**Location:**
- Separate directory: `backend/tests/` alongside `backend/src/`
- Not co-located with source files
- Directory structure mirrors domain (e.g., tests for analyzers are in root `tests/` not in nested `src/analysis/`)

**Naming:**
- Files: `test_*.py` prefix (pytest convention)
- Test functions: `test_*` prefix
- Test classes: `Test*` prefix (PascalCase)
- Fixtures: Use `@pytest.fixture` decorator

**Structure:**
```
backend/
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures
│   ├── test_api.py              # API route tests
│   ├── test_analyzers.py        # Manufacturing analyzer tests
│   ├── test_materials.py        # Material profile tests
│   ├── test_sam3d.py            # Segmentation tests
│   ├── test_rule_packs.py       # Rule pack tests
│   ├── test_context.py          # Geometry context tests
│   └── test_features.py         # Feature detection tests
└── src/
    └── ...
```

## Test Structure

**Suite Organization:**
```python
class TestYamlFilesLoad:
    """Verify every YAML file in materials/ parses without error."""
    
    def _yaml_files(self) -> list[Path]:
        materials_dir = Path(__file__).resolve().parent.parent / "src" / "profiles" / "materials"
        return sorted(materials_dir.glob("*.yaml"))
    
    def test_yaml_directory_has_15_files(self):
        files = self._yaml_files()
        assert len(files) == 15
    
    def test_all_yaml_files_parse(self):
        # Setup → Act → Assert
        import yaml
        for filepath in self._yaml_files():
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict)
```

**Patterns:**
- Setup: Fixtures or inline initialization
- Teardown: Usually not needed (pytest cleans up)
- Assertion: Direct `assert` statements or `assert X in Y` patterns

**Example from `test_sam3d.py`:**
```python
class TestConfig:
    def test_defaults(self):
        cfg = SAM3DConfig()
        assert cfg.enabled is False
        assert cfg.num_views == 24
```

## Mocking

**Framework:** `unittest.mock` from Python standard library

**Patterns:**
```python
from unittest import mock

# Monkeypatch (preferred for environment/imports)
def test_from_env_enabled(self, monkeypatch):
    monkeypatch.setenv("SAM3D_ENABLED", "true")
    monkeypatch.setenv("SAM3D_MODEL_PATH", "/weights/sam3d.pt")
    cfg = SAM3DConfig.from_env()
    assert cfg.enabled is True

# Reload modules after env changes
import importlib
importlib.reload(main)  # Force re-read of env vars
```

**Mock Usage (from `test_sam3d.py`):**
```python
with mock.patch.object(cache, 'get_cached_result') as mock_get:
    mock_get.return_value = None
    # Test logic that should call cache.get_cached_result()
```

**What to Mock:**
- Environment variables (use `monkeypatch`)
- File system operations (use `tmp_path` fixture)
- External API calls
- Module-level singletons that need reloading

**What NOT to Mock:**
- Core business logic (test the actual function)
- Data models and dataclasses
- Geometry calculations (test with real trimesh objects)

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture
def cube_10mm() -> trimesh.Trimesh:
    """Watertight 10mm cube — the universal 'it should just pass' fixture."""
    return trimesh.creation.box(extents=[10.0, 10.0, 10.0])

@pytest.fixture
def plate_thin_2mm() -> trimesh.Trimesh:
    """30×30×2 mm plate — exercises wall-thickness detection at the low end."""
    return trimesh.creation.box(extents=[30.0, 30.0, 2.0])

@pytest.fixture
def plate_with_hole(cube_10mm) -> trimesh.Trimesh:
    """50×50×10 plate with a 5mm-radius hole through it."""
    def build():
        plate = trimesh.creation.box(extents=[50.0, 50.0, 10.0])
        drill = trimesh.creation.cylinder(radius=5.0, height=12.0, sections=64)
        return plate.difference(drill)
    return _try_csg(build)
```

**Location:**
- Central fixtures in `backend/tests/conftest.py`
- Includes both primitive meshes and helper functions
- Optional fixture dependencies (e.g., `plate_with_hole` depends on `cube_10mm` parameter)

**Factory Pattern:**
- Helper functions for mesh serialization:
  ```python
  @pytest.fixture
  def stl_bytes_of():
      """Return a callable that serializes a mesh to binary STL bytes."""
      def _serialize(mesh: trimesh.Trimesh) -> bytes:
          buf = io.BytesIO()
          mesh.export(buf, file_type="stl")
          return buf.getvalue()
      return _serialize
  ```

**CSG/Boolean Operations:**
- Wrapped in `_try_csg()` helper that skips tests if manifold3d backend unavailable
  ```python
  def _try_csg(op):
      """Run a boolean-op closure, skip the test if the backend is missing."""
      try:
          return op()
      except Exception as e:
          pytest.skip(f"boolean ops unavailable: {e}")
  ```

## Coverage

**Requirements:** Not enforced; no coverage target in `pyproject.toml`

**View Coverage:**
```bash
pytest --cov=src tests/          # Generate coverage report
pytest --cov=src --cov-report=html tests/  # HTML coverage report
```

## Test Types

**Unit Tests:**
- Scope: Individual functions and classes
- Example: `TestConfig.test_defaults()` — tests SAM3DConfig defaults
- Approach: Isolated, fast, no external dependencies
- Files: `test_materials.py`, `test_context.py`, `test_features.py`

**Integration Tests:**
- Scope: API routes with full request/response cycle
- Example from `test_api.py`:
  ```python
  def test_validate_full_on_cube_returns_features(client, cube_10mm, stl_bytes_of):
      data = stl_bytes_of(cube_10mm)
      r = client.post(
          "/api/v1/validate",
          files={"file": ("cube.stl", data, "application/octet-stream")},
      )
      assert r.status_code == 200
      body = r.json()
      assert body["overall_verdict"] in {"pass", "issues"}
      assert "features" in body
  ```
- Uses FastAPI TestClient for HTTP testing
- Framework: `from fastapi.testclient import TestClient`

**E2E Tests:**
- Not used (frontend has no automated tests, backend tests cover API contract)

## Common Patterns

**Async Testing:**
- No async tests in current suite (FastAPI TestClient handles sync/async)
- Backend uses async routes but tests use blocking TestClient

**Error Testing:**
```python
def test_validate_rejects_bad_extension(client):
    r = client.post(
        "/api/v1/validate",
        files={"file": ("foo.txt", b"bad", "text/plain")},
    )
    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]
```

**Fixture with Environment Setup:**
```python
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)  # Force re-read of env
    return TestClient(main.app)
```

**Parametrized Tests (not heavily used):**
- Pattern available but not prominent in codebase
- Could use `@pytest.mark.parametrize()` for testing multiple inputs

**Skipping Tests:**
- Pattern: Use `pytest.skip()` when optional dependencies unavailable
  ```python
  def _try_csg(op):
      try:
          return op()
      except Exception as e:
          pytest.skip(f"boolean ops unavailable: {e}")
  ```

---

*Testing analysis: 2026-04-15*
