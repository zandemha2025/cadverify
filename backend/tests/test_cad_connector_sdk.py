import hashlib

import pytest

from src.services.cad_connector_sdk import (
    CadExportEnvelope,
    CadHost,
    CadSourceIdentity,
    HOST_PROGRAM,
)


def _envelope(payload: bytes, **overrides):
    values = {
        "source": CadSourceIdentity(CadHost.ONSHAPE, "w1", "d1", "r1", "e1"),
        "filename": "bracket.step",
        "media_type": "application/step",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byte_count": len(payload),
    }
    values.update(overrides)
    return CadExportEnvelope(**values)


def test_export_envelope_binds_payload_revision_and_neutral_format():
    payload = b"ISO-10303-21;revision-r1;"
    _envelope(payload).validate(payload)


@pytest.mark.parametrize("change", [
    {"sha256": "0" * 64},
    {"byte_count": 2},
    {"filename": "bracket.sldprt"},
    {"source": CadSourceIdentity(CadHost.ONSHAPE, "w1", "d1", "", "e1")},
])
def test_export_envelope_refuses_unverifiable_or_native_payload(change):
    payload = b"ISO-10303-21;revision-r1;"
    with pytest.raises(ValueError):
        _envelope(payload, **change).validate(payload)


def test_host_program_covers_the_major_cad_ecosystem_without_claiming_readiness():
    hosts = {entry.host for entry in HOST_PROGRAM}
    assert {CadHost.ONSHAPE, CadHost.SOLIDWORKS, CadHost.FUSION, CadHost.SIEMENS_NX} <= hosts
    assert len(hosts) == 10
    assert all(entry.implementation_state != "live" for entry in HOST_PROGRAM)
    assert all(entry.release_ready is False for entry in HOST_PROGRAM)
    assert all(entry.supported_host_versions == () for entry in HOST_PROGRAM)
    assert all(entry.verified_capabilities == frozenset() for entry in HOST_PROGRAM)
    assert all(entry.supports_version("latest") is False for entry in HOST_PROGRAM)


def test_public_catalog_separates_required_from_verified_capabilities():
    onshape = HOST_PROGRAM[0].as_public_dict()
    assert onshape["sdk_version"] == "1.0"
    assert onshape["implementation_state"] == "m2_in_progress"
    assert onshape["release_ready"] is False
    assert onshape["verified_capabilities"] == []
    assert onshape["required_capabilities"] == [
        "active_document", "neutral_export", "result_deeplink", "revision_identity"
    ]
