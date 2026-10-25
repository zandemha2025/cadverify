"""Security review R3, F2: the actuals XLSX reader refuses a DTD in any encoding.

The reader's DOCTYPE/ENTITY guard was a byte search, so a UTF-16 part passed it;
expat then expanded the internal entities (bounded only by its 100x
amplification limit), and a ~70 KB upload became a 100,000,000-character cell.

Route: POST /api/v1/actuals/preview (analyst) -> actuals_service.preview ->
read_table -> _read_xlsx -> _xml. Now expat itself is asked first: any DOCTYPE,
entity or notation declaration is refused in whatever encoding the part uses,
each part is read up to a size cap, and each cell up to Excel's own limit.
"""
from __future__ import annotations

import io
import time
import zipfile

import pytest

from src.services import actuals_service as svc

_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_WORKBOOK = f'<workbook {_NS}><sheets><sheet name="a" sheetId="1"/></sheets></workbook>'
_SHEET = (f'<worksheet {_NS}><sheetData>'
          '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>1</v></c></row>'
          '<row r="2"><c r="A2"><v>1</v></c><c r="B2"><v>2</v></c></row></sheetData></worksheet>')
_SHARED = f'<sst {_NS}><si><t>Part number</t></si></sst>'


def _xlsx(parts: dict[str, bytes | str] | None = None) -> bytes:
    """A minimal workbook; ``parts`` replaces or adds parts by their name under xl/."""
    files = {"workbook.xml": _WORKBOOK, "worksheets/sheet1.xml": _SHEET, "sharedStrings.xml": _SHARED}
    files.update(parts or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(f"xl/{name}", body)
    return buf.getvalue()


def _entity_doc(encoding: str, levels: int = 4) -> str:
    doc = f'<?xml version="1.0" encoding="{encoding}"?>\n<!DOCTYPE sst [\n<!ENTITY e0 "' + "A" * 1000 + '">\n'
    for i in range(1, levels):
        doc += f'<!ENTITY e{i} "' + f"&e{i - 1};" * 10 + '">\n'
    return doc + (f']>\n<sst {_NS}><si><t>&e{levels - 1};</t></si></sst>')


def test_a_plain_workbook_still_reads():
    t = svc.read_table("a.xlsx", _xlsx())
    assert t.headers == ["Part number", "1"] and t.rows == [["1", "2"]]


def test_a_utf16_workbook_without_a_dtd_still_reads():
    doc = '<?xml version="1.0" encoding="UTF-16"?>\n' + _SHARED
    t = svc.read_table("a.xlsx", _xlsx({"sharedStrings.xml": doc.encode("utf-16")}))
    assert t.headers == ["Part number", "1"]


def test_utf8_entity_declarations_are_refused():
    with pytest.raises(svc.TableError, match="XML features"):
        svc.read_table("a.xlsx", _xlsx({"sharedStrings.xml": _entity_doc("UTF-8").encode("utf-8")}))


@pytest.mark.parametrize("encoding, codec", [
    ("UTF-16", "utf-16"),        # with a byte-order mark: the reviewer's case (a 1,000,000-character header)
    ("UTF-16LE", "utf-16-le"),   # no byte-order mark
    ("UTF-16BE", "utf-16-be"),
])
def test_utf16_entity_declarations_are_refused(encoding, codec):
    data = _xlsx({"sharedStrings.xml": _entity_doc(encoding).encode(codec)})
    t = time.monotonic()
    with pytest.raises(svc.TableError, match="XML features"):
        svc.read_table("a.xlsx", data)
    assert time.monotonic() - t < 1.0


def test_a_utf16_billion_laughs_is_refused_before_anything_expands():
    data = _xlsx({"sharedStrings.xml": _entity_doc("UTF-16", levels=7).encode("utf-16")})
    t = time.monotonic()
    with pytest.raises(svc.TableError, match="XML features"):
        svc.read_table("a.xlsx", data)
    assert time.monotonic() - t < 0.5


_RELS_WORKBOOK = _WORKBOOK.replace(
    'sheetId="1"', 'sheetId="1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId1"')


@pytest.mark.parametrize("part", ["workbook.xml", "worksheets/sheet1.xml", "styles.xml", "_rels/workbook.xml.rels"])
def test_a_dtd_in_any_part_is_refused(part):
    body = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x SYSTEM "http://example.invalid/x.dtd">'
    body += {"workbook.xml": _RELS_WORKBOOK, "worksheets/sheet1.xml": _SHEET}.get(part, f"<x {_NS}/>")
    # The workbook names a relationship, so its .rels part is read too.
    data = _xlsx({"workbook.xml": _RELS_WORKBOOK, part: body.encode("utf-16")})
    with pytest.raises(svc.TableError, match="XML features"):
        svc.read_table("a.xlsx", data)


def test_a_cell_longer_than_excel_allows_is_refused():
    shared = f'<sst {_NS}><si><t>{"A" * (svc.MAX_CELL_CHARS + 1)}</t></si></sst>'
    with pytest.raises(svc.TableError, match="32,767 characters"):
        svc.read_table("a.xlsx", _xlsx({"sharedStrings.xml": shared}))
    inline = _SHEET.replace('<c r="B2"><v>2</v></c>',
                            f'<c r="B2" t="inlineStr"><is><t>{"B" * (svc.MAX_CELL_CHARS + 1)}</t></is></c>')
    with pytest.raises(svc.TableError, match="32,767 characters"):
        svc.read_table("a.xlsx", _xlsx({"worksheets/sheet1.xml": inline}))


def test_a_part_over_the_part_cap_is_refused(monkeypatch):
    monkeypatch.setattr(svc, "_XLSX_MAX_PART", 1024)
    shared = f'<sst {_NS}>' + "<si><t>x</t></si>" * 200 + "</sst>"
    with pytest.raises(svc.TableError, match="too large"):
        svc.read_table("a.xlsx", _xlsx({"sharedStrings.xml": shared}))


# ── the other XML reader a customer's file reaches: a 3MF for the fit check ─────

_3MF_RELS = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
             'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
_3MF_MODEL = ('<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
              '<resources><object id="1" type="model"><mesh><vertices><vertex x="0" y="0" z="0"/>'
              '<vertex x="10" y="0" z="0"/><vertex x="0" y="10" z="0"/><vertex x="0" y="0" z="10"/></vertices>'
              '<triangles><triangle v1="0" v2="2" v3="1"/><triangle v1="0" v2="1" v3="3"/>'
              '<triangle v1="0" v2="3" v3="2"/><triangle v1="1" v2="2" v3="3"/></triangles></mesh></object>'
              '</resources><build><item objectid="1"/></build></model>')


def _3mf(model: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_rels/.rels", _3MF_RELS)
        z.writestr("3D/3dmodel.model", model)
    return buf.getvalue()


def test_a_plain_3mf_still_loads():
    from src.services.fit_service import parse_supplementary_mesh

    assert len(parse_supplementary_mesh(_3mf(_3MF_MODEL.encode()), "a.3mf").faces) == 4


@pytest.mark.parametrize("doctype, codec", [
    ('<!DOCTYPE model [<!ENTITY x SYSTEM "file:///etc/passwd">]>', "utf-16"),  # loaded before: entity unread
    ('<!DOCTYPE model SYSTEM "http://example.invalid/3mf.dtd">', "utf-8"),
], ids=["utf16-external-entity", "utf8-external-dtd"])
def test_a_3mf_with_a_dtd_is_refused_before_the_mesh_loader_reads_it(doctype, codec):
    from src.services.fit_service import FitGeometryError, parse_supplementary_mesh

    encoding = "UTF-16" if codec == "utf-16" else "UTF-8"
    model = f'<?xml version="1.0" encoding="{encoding}"?>{doctype}{_3MF_MODEL}'.encode(codec)
    with pytest.raises(FitGeometryError, match="DOCTYPE"):
        parse_supplementary_mesh(_3mf(model), "a.3mf")
