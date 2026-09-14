"""Shared contracts for CAD-host connectors.

Host plugins export a revision-pinned neutral CAD file and an envelope. The
server verifies both before normal analysis. No host-specific adapter may invent
geometry, bypass the standard parser, or claim a saved record without the
returned source identity.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol

SDK_VERSION = "1.0"
SUPPORTED_EXCHANGE_SUFFIXES = ("stl", "step", "stp", "iges", "igs")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CadHost(str, Enum):
    ONSHAPE = "onshape"
    SOLIDWORKS = "solidworks"
    FUSION = "fusion"
    SIEMENS_NX = "siemens_nx"
    CREO = "creo"
    CATIA = "catia"
    INVENTOR = "inventor"
    SOLID_EDGE = "solid_edge"
    RHINO = "rhino"
    FREECAD = "freecad"


class ConnectorCapability(str, Enum):
    ACTIVE_DOCUMENT = "active_document"
    REVISION_IDENTITY = "revision_identity"
    NEUTRAL_EXPORT = "neutral_export"
    RESULT_DEEPLINK = "result_deeplink"


@dataclass(frozen=True)
class CadSourceIdentity:
    host: CadHost
    workspace_id: str
    document_id: str
    revision_id: str
    element_id: str | None = None
    configuration: str | None = None


@dataclass(frozen=True)
class CadExportEnvelope:
    source: CadSourceIdentity
    filename: str
    media_type: str
    sha256: str
    byte_count: int
    units: str | None = None

    @property
    def suffix(self) -> str:
        return self.filename.rsplit(".", 1)[-1].lower() if "." in self.filename else ""

    def validate(self, payload: bytes) -> None:
        if not all((self.source.workspace_id, self.source.document_id, self.source.revision_id)):
            raise ValueError("connector export requires workspace, document, and revision identity")
        if self.suffix not in SUPPORTED_EXCHANGE_SUFFIXES:
            raise ValueError("connector export must be STL, STEP/STP, or IGES/IGS")
        if self.byte_count <= 0 or self.byte_count != len(payload):
            raise ValueError("connector export byte count does not match payload")
        digest = hashlib.sha256(payload).hexdigest()
        if not SHA256_RE.fullmatch(self.sha256) or digest != self.sha256:
            raise ValueError("connector export SHA-256 does not match payload")


@dataclass(frozen=True)
class CadConnectorDescriptor:
    host: CadHost
    display_name: str
    required_capabilities: frozenset[ConnectorCapability]
    verified_capabilities: frozenset[ConnectorCapability] = frozenset()
    exchange_formats: tuple[str, ...] = ("step",)
    supported_host_versions: tuple[str, ...] = ()
    implementation_state: str = "contract_only"

    @property
    def release_ready(self) -> bool:
        return (
            self.implementation_state == "live"
            and bool(self.supported_host_versions)
            and self.required_capabilities <= self.verified_capabilities
        )

    def supports_version(self, version: str) -> bool:
        return bool(version) and version in self.supported_host_versions

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "sdk_version": SDK_VERSION,
            "host": self.host.value,
            "display_name": self.display_name,
            "required_capabilities": sorted(item.value for item in self.required_capabilities),
            "verified_capabilities": sorted(item.value for item in self.verified_capabilities),
            "exchange_formats": list(self.exchange_formats),
            "supported_host_versions": list(self.supported_host_versions),
            "implementation_state": self.implementation_state,
            "release_ready": self.release_ready,
        }


class CadHostAdapter(Protocol):
    descriptor: CadConnectorDescriptor

    async def export_active_document(
        self,
        *,
        access_token: str,
        context: Mapping[str, Any],
    ) -> tuple[CadExportEnvelope, bytes]:
        """Return a source-bound neutral export; never a host-native document."""
        ...


RELEASE_CAPABILITIES = frozenset(ConnectorCapability)

HOST_PROGRAM: tuple[CadConnectorDescriptor, ...] = (
    CadConnectorDescriptor(CadHost.ONSHAPE, "Onshape", RELEASE_CAPABILITIES, implementation_state="m2_in_progress"),
    CadConnectorDescriptor(CadHost.SOLIDWORKS, "SOLIDWORKS", RELEASE_CAPABILITIES),
    CadConnectorDescriptor(CadHost.FUSION, "Autodesk Fusion", RELEASE_CAPABILITIES),
    CadConnectorDescriptor(CadHost.SIEMENS_NX, "Siemens NX", RELEASE_CAPABILITIES),
    CadConnectorDescriptor(CadHost.CREO, "PTC Creo", RELEASE_CAPABILITIES),
    CadConnectorDescriptor(CadHost.CATIA, "CATIA", RELEASE_CAPABILITIES),
    CadConnectorDescriptor(CadHost.INVENTOR, "Autodesk Inventor", RELEASE_CAPABILITIES),
    CadConnectorDescriptor(CadHost.SOLID_EDGE, "Solid Edge", RELEASE_CAPABILITIES),
    CadConnectorDescriptor(CadHost.RHINO, "Rhino", RELEASE_CAPABILITIES),
    CadConnectorDescriptor(CadHost.FREECAD, "FreeCAD", RELEASE_CAPABILITIES),
)
