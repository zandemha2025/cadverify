"""STEP export through Fusion's ExportManager — isolated for testability.

Inside Fusion this uses the real ExportManager (AP242). Outside Fusion the
unit tests exercise :func:`target_path` and the bytes-reading only; the
adsk-touching function is thin by design (the in-tool smoke test covers it).
"""
from __future__ import annotations

import os
import tempfile


def target_path() -> str:
    """A temp path for the silent export (cleaned by the caller)."""
    fd, path = tempfile.mkstemp(prefix="scalecad_", suffix=".step")
    os.close(fd)
    return path


def export_active_design_step(design, _addin_dir: str) -> tuple[bytes, str]:
    """The design as STEP AP242 bytes. ``design`` is adsk.fusion.Design."""
    import adsk.core  # noqa: F401  (Fusion runtime only)

    path = target_path()
    try:
        manager = design.exportManager
        options = manager.createSTEPExportOptions(
            path, design.rootComponent)  # AP242 by Fusion's STEP exporter
        if not manager.execute(options):
            raise RuntimeError("Fusion's STEP export did not complete.")
        with open(path, "rb") as fh:
            return fh.read(), os.path.basename(design.parentDocument.name or "part") + ".step"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
