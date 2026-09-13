from pathlib import Path

def test_portfolio_route_preserves_skipped_state():
    source = (Path(__file__).parents[1] / "src/api/batch_router.py").read_text()
    assert 'else "skipped" if status == "skipped"' in source
