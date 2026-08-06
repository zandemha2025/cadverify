"""Regression contracts for the single authenticated ProofShape shell."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_verify_and_design_studio_share_the_same_app_shell() -> None:
    app_layout = _read("frontend/src/app/(app)/layout.tsx")
    verify_layout = _read("frontend/src/app/(verify)/layout.tsx")

    shared_mount = "<AppShell>{children}</AppShell>"
    assert shared_mount in app_layout
    assert shared_mount in verify_layout


def test_verify_owns_workspace_navigation_not_platform_chrome() -> None:
    verify_app = _read("frontend/src/components/verify/verify-app.tsx")

    assert 'className="cv-verify-workspace-nav"' in verify_app
    assert 'className="cv-verify-mobile-section"' in verify_app
    assert "VerifyAccountMenu" not in verify_app
    assert "NotificationsPanel" not in verify_app


def test_authenticated_product_is_light_first() -> None:
    root_layout = _read("frontend/src/app/layout.tsx")

    assert "localStorage.getItem('cv_theme')==='dark'" in root_layout
    assert "localStorage.getItem('cv_theme')!=='light'" not in root_layout
