"""Local TripoSR reconstruction backend (GPU inference).

Loads the TripoSR model from HuggingFace (or a local path) and runs
single-image 3D reconstruction on the local machine.  Heavy inference
is offloaded to a thread pool so the async event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time

from PIL import Image

from src.reconstruction.engine import (
    ReconstructionEngine,
    ReconstructParams,
    ReconstructResult,
)

logger = logging.getLogger(__name__)


class LocalTripoSR(ReconstructionEngine):
    """ReconstructionEngine backed by a local TripoSR model."""

    def __init__(self, model_path: str | None = None) -> None:
        self._model_path = model_path or os.getenv(
            "TRIPOSR_MODEL_PATH", "stabilityai/TripoSR"
        )
        self._model = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls) -> "LocalTripoSR":
        """Create an instance and eagerly load the model."""
        instance = cls()
        instance._ensure_model_loaded()
        return instance

    # ------------------------------------------------------------------
    # Model loading (lazy)
    # ------------------------------------------------------------------

    def _ensure_model_loaded(self) -> None:
        if self._model is not None:
            return
        from tsr.system import TSR

        self._model = TSR.from_pretrained(
            self._model_path,
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
        self._model.renderer.set_chunk_size(8192)
        logger.info("TripoSR model loaded from %s", self._model_path)

    # ------------------------------------------------------------------
    # Device
    # ------------------------------------------------------------------

    @property
    def _device(self) -> str:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    # ------------------------------------------------------------------
    # Inference (sync, run in thread pool)
    # ------------------------------------------------------------------

    def _infer(self, image: Image.Image, params: ReconstructParams) -> ReconstructResult:
        import torch
        import trimesh as tm

        t0 = time.perf_counter()
        with torch.no_grad():
            scene_codes = self._model([image], device=self._device)
            meshes = self._model.extract_mesh(
                scene_codes, resolution=params.resolution
            )

        mesh = meshes[0]
        # Export to STL bytes via trimesh
        tri_mesh = tm.Trimesh(
            vertices=mesh.vertices, faces=mesh.faces
        )
        buf = io.BytesIO()
        tri_mesh.export(buf, file_type="stl")
        stl_bytes = buf.getvalue()

        duration_ms = (time.perf_counter() - t0) * 1000
        return ReconstructResult(
            mesh_bytes=stl_bytes,
            face_count=len(tri_mesh.faces),
            duration_ms=duration_ms,
            method="triposr_local",
        )

    # ------------------------------------------------------------------
    # ReconstructionEngine interface
    # ------------------------------------------------------------------

    async def reconstruct(
        self, image_bytes: bytes, params: ReconstructParams
    ) -> ReconstructResult:
        """Reconstruct mesh from image bytes using the local TripoSR model."""
        self._ensure_model_loaded()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._infer, image, params)

    async def health_check(self) -> bool:
        """Return True if the model has been loaded."""
        return self._model is not None
