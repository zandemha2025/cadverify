"""SAM-3D pipeline configuration.

All settings can be overridden via environment variables so that the pipeline
stays disabled (safe default) until explicitly opted in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class SAM3DConfig:
    """Configuration for the SAM-3D semantic segmentation pipeline."""

    enabled: bool = False
    model_path: str = ""
    num_views: int = 24
    num_points: int = 10000
    min_segment_faces: int = 5
    confidence_threshold: float = 0.7
    cache_dir: str = "/tmp/cadverify_sam3d_cache"

    @classmethod
    def from_env(cls) -> SAM3DConfig:
        """Build config from environment variables.

        Environment variables:
            SAM3D_ENABLED     - "true" to enable (default "false")
            SAM3D_MODEL_PATH  - path to classifier weights
            SAM3D_CACHE_DIR   - directory for content-addressable cache
        """
        return cls(
            enabled=os.getenv("SAM3D_ENABLED", "false").lower() == "true",
            model_path=os.getenv("SAM3D_MODEL_PATH", ""),
            cache_dir=os.getenv("SAM3D_CACHE_DIR", "/tmp/cadverify_sam3d_cache"),
        )
