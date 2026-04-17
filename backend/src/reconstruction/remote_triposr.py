"""Remote TripoSR reconstruction backend (Replicate API).

Fallback when no local GPU is available.  Sends the image to the
Replicate hosted TripoSR model and polls for the result.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import time
from typing import Any

import httpx

from src.reconstruction.engine import (
    ReconstructionEngine,
    ReconstructParams,
    ReconstructResult,
)

logger = logging.getLogger(__name__)

_REPLICATE_BASE = "https://api.replicate.com/v1"
_POLL_INTERVAL_SEC = 2.0


class RemoteTripoSR(ReconstructionEngine):
    """ReconstructionEngine backed by Replicate's hosted TripoSR model."""

    def __init__(self) -> None:
        self._api_token: str | None = os.getenv("REPLICATE_API_TOKEN")
        if self._api_token is None:
            raise RuntimeError(
                "REPLICATE_API_TOKEN env var required for remote reconstruction"
            )
        self._model_version: str = os.getenv(
            "TRIPOSR_REPLICATE_MODEL", "stability-ai/triposr"
        )
        self._timeout: int = int(os.getenv("RECONSTRUCTION_TIMEOUT_SEC", "120"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_token}"}

    @staticmethod
    def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
        """Return a copy of *headers* with authorization values masked."""
        redacted = dict(headers)
        for key in ("Authorization", "authorization"):
            if key in redacted:
                redacted[key] = "Bearer ***REDACTED***"
        return redacted

    # ------------------------------------------------------------------
    # ReconstructionEngine interface
    # ------------------------------------------------------------------

    async def reconstruct(
        self, image_bytes: bytes, params: ReconstructParams
    ) -> ReconstructResult:
        """Send image to Replicate API and poll until complete."""
        t0 = time.perf_counter()

        b64_image = base64.b64encode(image_bytes).decode("ascii")
        data_uri = f"data:image/png;base64,{b64_image}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Create prediction
            try:
                resp = await client.post(
                    f"{_REPLICATE_BASE}/predictions",
                    headers=self._auth_headers(),
                    json={
                        "version": self._model_version,
                        "input": {
                            "image": data_uri,
                            "mc_resolution": params.resolution,
                            "output_format": params.output_format,
                        },
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Replicate API error (status %s): %s",
                    exc.response.status_code,
                    exc.response.text,
                )
                raise RuntimeError(
                    f"Replicate API returned {exc.response.status_code}"
                ) from exc

            prediction: dict[str, Any] = resp.json()
            prediction_url = prediction.get("urls", {}).get("get", "")

            # 2. Poll until succeeded / failed / timeout
            deadline = time.perf_counter() + self._timeout
            status = prediction.get("status", "starting")

            while status not in ("succeeded", "failed", "canceled"):
                if time.perf_counter() > deadline:
                    raise httpx.TimeoutException(
                        f"Reconstruction timed out after {self._timeout}s"
                    )
                import asyncio

                await asyncio.sleep(_POLL_INTERVAL_SEC)

                try:
                    poll_resp = await client.get(
                        prediction_url, headers=self._auth_headers()
                    )
                    poll_resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "Poll error (headers redacted): %s",
                        self._redact_headers(dict(exc.request.headers)),
                    )
                    raise RuntimeError(
                        f"Replicate poll returned {exc.response.status_code}"
                    ) from exc

                prediction = poll_resp.json()
                status = prediction.get("status", "failed")

            if status != "succeeded":
                error_detail = prediction.get("error", "Unknown failure")
                raise RuntimeError(
                    f"Replicate prediction failed: {error_detail}"
                )

            # 3. Download output mesh
            output_url = prediction.get("output")
            if isinstance(output_url, list):
                output_url = output_url[0]
            if not output_url:
                raise RuntimeError("No output URL in Replicate response")

            dl_resp = await client.get(output_url)
            dl_resp.raise_for_status()
            raw_bytes = dl_resp.content

        # 4. Convert to STL if needed
        stl_bytes, face_count = self._to_stl(raw_bytes)

        duration_ms = (time.perf_counter() - t0) * 1000
        return ReconstructResult(
            mesh_bytes=stl_bytes,
            face_count=face_count,
            duration_ms=duration_ms,
            method="triposr_remote",
        )

    async def health_check(self) -> bool:
        """Check that the API token is configured and Replicate is reachable."""
        if not self._api_token:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{_REPLICATE_BASE}/models/{self._model_version}",
                    headers=self._auth_headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Format conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_stl(raw_bytes: bytes) -> tuple[bytes, int]:
        """Convert OBJ / GLB / STL bytes to STL, returning (stl_bytes, face_count)."""
        import trimesh

        mesh = trimesh.load(
            io.BytesIO(raw_bytes),
            file_type=None,  # auto-detect
            force="mesh",
        )
        buf = io.BytesIO()
        mesh.export(buf, file_type="stl")
        return buf.getvalue(), len(mesh.faces)
