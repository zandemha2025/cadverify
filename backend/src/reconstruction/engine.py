"""ReconstructionEngine protocol and shared data types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ReconstructParams:
    """Parameters for mesh reconstruction from an image."""

    resolution: int = 256  # TripoSR mesh resolution: 128, 256, or 512
    output_format: str = "stl"  # output mesh format


@dataclass
class ReconstructResult:
    """Result of a reconstruction operation."""

    mesh_bytes: bytes
    face_count: int
    duration_ms: float
    method: str  # e.g. "triposr_local", "triposr_remote"


class ReconstructionEngine(ABC):
    """Abstract base class for 3D reconstruction backends.

    Mirrors the JobQueue protocol pattern from src.jobs.protocols.
    Implementations provide either local GPU inference or remote API calls.
    """

    @abstractmethod
    async def reconstruct(
        self, image_bytes: bytes, params: ReconstructParams
    ) -> ReconstructResult:
        """Reconstruct a 3D mesh from a single image.

        Args:
            image_bytes: Raw image file bytes (JPEG/PNG/WebP).
            params: Reconstruction parameters.

        Returns:
            ReconstructResult with STL mesh bytes and metadata.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check whether the reconstruction backend is available."""
        ...
