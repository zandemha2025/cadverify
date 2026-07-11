"""Parse STEP AP242 files using OCP XDE framework for B-rep geometry and PMI.

Uses STEPCAFControl_Reader (XDE-aware) to extract shape hierarchy and
detect GD&T/PMI presence. Coexists with step_parser.py which handles
mesh tessellation via cadquery.
"""

from __future__ import annotations

import os
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HAS_XDE = False
STEPCAFControl_Reader: Any = None
TDocStd_Document: Any = None
XCAFApp_Application: Any = None
XCAFDoc_DimTolTool: Any = None
XCAFDoc_ShapeTool: Any = None
TCollection_ExtendedString: Any = None
IFSelect_RetDone: Any = None
TDF_LabelSequence: Any = None
try:
    STEPCAFControl_Reader = getattr(
        importlib.import_module("OCP.STEPCAFControl"), "STEPCAFControl_Reader"
    )
    TDocStd_Document = getattr(
        importlib.import_module("OCP.TDocStd"), "TDocStd_Document"
    )
    XCAFApp_Application = getattr(
        importlib.import_module("OCP.XCAFApp"), "XCAFApp_Application"
    )
    _xcaf_doc = importlib.import_module("OCP.XCAFDoc")
    XCAFDoc_DimTolTool = getattr(_xcaf_doc, "XCAFDoc_DimTolTool")
    XCAFDoc_ShapeTool = getattr(_xcaf_doc, "XCAFDoc_ShapeTool")
    TCollection_ExtendedString = getattr(
        importlib.import_module("OCP.TCollection"), "TCollection_ExtendedString"
    )
    IFSelect_RetDone = getattr(
        importlib.import_module("OCP.IFSelect"), "IFSelect_RetDone"
    )
    TDF_LabelSequence = getattr(
        importlib.import_module("OCP.TDF"), "TDF_LabelSequence"
    )
    _HAS_XDE = True
except (ImportError, AttributeError):
    pass


def is_ap242_supported() -> bool:
    """Check if AP242 XDE parsing is available (OCP with XDE modules)."""
    return _HAS_XDE


@dataclass
class AP242Document:
    """Result of parsing a STEP AP242 file via XDE framework.

    Attributes:
        doc: TDocStd_Document reference (XDE document).
        shape_tool: XCAFDoc_ShapeTool for traversing shape hierarchy.
        dim_tol_tool: XCAFDoc_DimTolTool for GD&T/PMI access.
        has_pmi: True if the document contains GD&T labels.
        shape_labels: Top-level (free) shape labels from the document.
    """

    doc: Any
    shape_tool: Any
    dim_tol_tool: Any
    has_pmi: bool
    shape_labels: list = field(default_factory=list)


def _require_xde() -> None:
    """Raise RuntimeError if XDE modules are not available."""
    if not _HAS_XDE:
        raise RuntimeError(
            "AP242 parsing requires OCP XDE modules. "
            "Install cadquery-ocp or OCP with XDE support."
        )


def parse_ap242(file_path: str | Path) -> AP242Document:
    """Parse a STEP file using XDE framework for B-rep geometry and PMI.

    Supports both AP242 (with PMI) and AP214 (geometry only).

    Args:
        file_path: Path to .step or .stp file.

    Returns:
        AP242Document with shape hierarchy and PMI detection.

    Raises:
        RuntimeError: If OCP XDE modules are not installed.
        FileNotFoundError: If file does not exist.
        ValueError: If file extension is wrong or STEP read fails.
    """
    _require_xde()

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"STEP file not found: {path}")
    if path.suffix.lower() not in (".step", ".stp"):
        raise ValueError(f"Expected .step/.stp file, got: {path.suffix}")

    # Create XDE application and document
    app = XCAFApp_Application.GetApplication()
    doc = TDocStd_Document(TCollection_ExtendedString("XDE"))
    app.InitDocument(doc)

    # Read STEP file with XDE-aware reader
    reader = STEPCAFControl_Reader()
    status = reader.ReadFile(str(path))
    if status != IFSelect_RetDone:
        raise ValueError(
            f"Failed to read STEP file: {path} (status={status})"
        )

    reader.Transfer(doc)

    # Extract tools from document main label
    shape_tool = XCAFDoc_ShapeTool.Set(doc.Main())
    dim_tol_tool = XCAFDoc_DimTolTool.Set(doc.Main())

    # Detect PMI presence via GDT labels
    gdt_labels = TDF_LabelSequence()
    dim_tol_tool.GetDimTolLabels(gdt_labels)
    has_pmi = gdt_labels.Length() > 0

    # Get top-level (free) shape labels
    free_shapes = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_shapes)
    shape_labels = [free_shapes.Value(i) for i in range(1, free_shapes.Length() + 1)]

    return AP242Document(
        doc=doc,
        shape_tool=shape_tool,
        dim_tol_tool=dim_tol_tool,
        has_pmi=has_pmi,
        shape_labels=shape_labels,
    )


def parse_ap242_from_bytes(data: bytes, filename: str = "upload.step") -> AP242Document:
    """Parse STEP AP242 from raw bytes by writing to a temp file.

    STEP parsing requires file access (OpenCascade limitation).

    Args:
        data: Raw bytes of the STEP file.
        filename: Original filename (used for extension detection).

    Returns:
        AP242Document with shape hierarchy and PMI detection.
    """
    _require_xde()

    import tempfile

    suffix = Path(filename).suffix or ".step"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w+b")
    try:
        os.chmod(tmp.name, 0o600)  # owner R/W only — security best practice
        tmp.write(data)
        tmp.flush()
        tmp.close()  # close FD before OpenCascade re-opens by path
        return parse_ap242(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass
