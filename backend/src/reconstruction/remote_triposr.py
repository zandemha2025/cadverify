"""Remote TripoSR reconstruction backend (Replicate API).

Fallback when no local GPU is available.  Sends the image to the
Replicate hosted TripoSR model and polls for the result.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image

from src.reconstruction.engine import (
    ReconstructionEngine,
    ReconstructParams,
    ReconstructResult,
)

logger = logging.getLogger(__name__)

_REPLICATE_BASE = "https://api.replicate.com/v1"
_POLL_INTERVAL_SEC = 2.0
_MODEL_RE = re.compile(
    r"^(?P<owner>[a-z0-9](?:[a-z0-9-]{0,62}))/(?P<name>[a-z0-9](?:[a-z0-9._-]{0,127}))"
    r":(?P<version>[a-f0-9]{64})$"
)
_PREDICTION_ID_RE = re.compile(r"^[a-z0-9]{8,64}$")
_DATA_URL_LIMIT = 256 * 1024
_OUTPUT_TYPES = {"stl", "obj", "glb", "gltf", "ply"}


def _pinned_model() -> tuple[str, str, str, str]:
    raw = os.getenv("TRIPOSR_REPLICATE_MODEL", "").strip().lower()
    match = _MODEL_RE.fullmatch(raw)
    if match is None:
        raise RuntimeError(
            "TRIPOSR_REPLICATE_MODEL must be owner/model:<64-hex-version>"
        )
    return match["owner"], match["name"], match["version"], raw


def _prediction_url(prediction_id: str, suffix: str = "") -> str:
    if _PREDICTION_ID_RE.fullmatch(prediction_id) is None:
        raise RuntimeError("Reconstruction provider returned an invalid prediction id")
    return f"{_REPLICATE_BASE}/predictions/{prediction_id}{suffix}"


def _trusted_output_url(raw: object) -> str:
    if not isinstance(raw, str):
        raise RuntimeError("Reconstruction provider returned no mesh URL")
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise RuntimeError("Reconstruction provider returned an invalid mesh URL") from exc
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.fragment
        or not (
            hostname == "replicate.delivery"
            or hostname.endswith(".replicate.delivery")
        )
    ):
        raise RuntimeError(
            "Reconstruction provider returned a mesh URL outside its approved delivery domain"
        )
    return raw


def _mesh_output_url(output: object) -> str:
    """Extract one provider mesh URL without accepting arbitrary nested data."""
    if isinstance(output, str):
        return _trusted_output_url(output)
    if isinstance(output, list):
        candidates = [item for item in output if isinstance(item, str)]
    elif isinstance(output, dict):
        candidates = [
            output.get(key)
            for key in ("mesh", "model", "stl", "obj", "glb", "output")
            if isinstance(output.get(key), str)
        ]
    else:
        candidates = []
    for candidate in candidates:
        path = urlsplit(candidate).path.lower()
        if any(path.endswith(f".{suffix}") for suffix in _OUTPUT_TYPES):
            return _trusted_output_url(candidate)
    raise RuntimeError("Reconstruction provider returned no supported mesh output")


class RemoteTripoSR(ReconstructionEngine):
    """ReconstructionEngine backed by Replicate's hosted TripoSR model."""

    def __init__(self) -> None:
        self._api_token = os.getenv("REPLICATE_API_TOKEN", "").strip()
        if not self._api_token:
            raise RuntimeError(
                "REPLICATE_API_TOKEN env var required for remote reconstruction"
            )
        (
            self._model_owner,
            self._model_name,
            self._version_id,
            self._model_version,
        ) = _pinned_model()
        self._timeout = max(
            5, min(900, int(os.getenv("RECONSTRUCTION_TIMEOUT_SEC", "120")))
        )
        self._max_output_bytes = max(
            1024 * 1024,
            min(
                500 * 1024 * 1024,
                int(os.getenv("RECONSTRUCTION_MAX_OUTPUT_BYTES", str(100 * 1024 * 1024))),
            ),
        )

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

    @staticmethod
    def _image_data_uri(image_bytes: bytes) -> str:
        """Produce a bounded JPEG data URL accepted by the provider API."""
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise RuntimeError("Preprocessed reconstruction image is invalid") from exc
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        encoded = b""
        for quality in (90, 82, 74, 66, 58):
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            encoded = buffer.getvalue()
            if len(encoded) <= _DATA_URL_LIMIT:
                break
        if not encoded or len(encoded) > _DATA_URL_LIMIT:
            raise RuntimeError(
                "Preprocessed reconstruction image exceeds the provider data-URL limit"
            )
        return f"data:image/jpeg;base64,{base64.b64encode(encoded).decode('ascii')}"

    async def _cancel_prediction(
        self, client: httpx.AsyncClient, prediction_id: str
    ) -> None:
        try:
            await client.post(
                _prediction_url(prediction_id, "/cancel"),
                headers=self._auth_headers(),
            )
        except Exception:
            logger.warning(
                "Could not cancel remote reconstruction prediction %s",
                prediction_id,
                exc_info=True,
            )

    async def _download_output(
        self, client: httpx.AsyncClient, output_url: str
    ) -> tuple[bytes, str | None]:
        chunks: list[bytes] = []
        total = 0
        async with client.stream(
            "GET", output_url, headers=self._auth_headers()
        ) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and int(declared) > self._max_output_bytes:
                raise RuntimeError("Reconstruction output exceeds the configured limit")
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > self._max_output_bytes:
                    raise RuntimeError(
                        "Reconstruction output exceeds the configured limit"
                    )
                chunks.append(chunk)
            return b"".join(chunks), response.headers.get("content-type")

    # ------------------------------------------------------------------
    # ReconstructionEngine interface
    # ------------------------------------------------------------------

    async def reconstruct(
        self, image_bytes: bytes, params: ReconstructParams
    ) -> ReconstructResult:
        """Send image to Replicate API and poll until complete."""
        t0 = time.perf_counter()

        data_uri = self._image_data_uri(image_bytes)

        timeout = httpx.Timeout(30.0, read=max(30.0, float(self._timeout)))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            # 1. Create prediction
            try:
                resp = await client.post(
                    f"{_REPLICATE_BASE}/predictions",
                    headers={
                        **self._auth_headers(),
                        "Cancel-After": f"{self._timeout}s",
                    },
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
                    "Replicate API error creating prediction (status %s)",
                    exc.response.status_code,
                )
                raise RuntimeError(
                    "Remote reconstruction provider rejected the request"
                ) from exc

            prediction: dict[str, Any] = resp.json()
            prediction_id = prediction.get("id")
            if not isinstance(prediction_id, str):
                raise RuntimeError(
                    "Reconstruction provider returned no prediction id"
                )
            prediction_url = _prediction_url(prediction_id)

            # 2. Poll until succeeded / failed / timeout
            deadline = time.perf_counter() + self._timeout
            status = prediction.get("status", "starting")

            try:
                while status not in ("succeeded", "failed", "canceled"):
                    if time.perf_counter() > deadline:
                        raise httpx.TimeoutException(
                            f"Reconstruction timed out after {self._timeout}s"
                        )
                    await asyncio.sleep(_POLL_INTERVAL_SEC)

                    try:
                        poll_resp = await client.get(
                            prediction_url, headers=self._auth_headers()
                        )
                        poll_resp.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        logger.error(
                            "Remote reconstruction poll failed (status %s; headers %s)",
                            exc.response.status_code,
                            self._redact_headers(dict(exc.request.headers)),
                        )
                        raise RuntimeError(
                            "Remote reconstruction provider polling failed"
                        ) from exc

                    prediction = poll_resp.json()
                    status = prediction.get("status", "failed")
            except BaseException:
                if status not in ("succeeded", "failed", "canceled"):
                    await asyncio.shield(
                        self._cancel_prediction(client, prediction_id)
                    )
                raise

            if status != "succeeded":
                raise RuntimeError(
                    "Remote reconstruction provider reported a terminal failure"
                )

            # 3. Download output mesh
            output_url = _mesh_output_url(prediction.get("output"))
            raw_bytes, content_type = await self._download_output(client, output_url)

        # 4. Convert to STL if needed
        stl_bytes, face_count = self._to_stl(
            raw_bytes,
            output_url=output_url,
            content_type=content_type,
        )

        duration_ms = (time.perf_counter() - t0) * 1000
        return ReconstructResult(
            mesh_bytes=stl_bytes,
            face_count=face_count,
            duration_ms=duration_ms,
            method="triposr_remote",
        )

    async def health_check(self) -> bool:
        """Check that the pinned provider model version remains reachable."""
        if not self._api_token:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{_REPLICATE_BASE}/models/{self._model_owner}/"
                    f"{self._model_name}/versions/{self._version_id}",
                    headers=self._auth_headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Format conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_stl(
        raw_bytes: bytes,
        *,
        output_url: str,
        content_type: str | None,
    ) -> tuple[bytes, int]:
        """Convert OBJ / GLB / STL bytes to STL, returning (stl_bytes, face_count)."""
        import trimesh

        suffix = urlsplit(output_url).path.rsplit(".", 1)[-1].lower()
        content_types = {
            "model/stl": "stl",
            "application/sla": "stl",
            "model/obj": "obj",
            "model/gltf-binary": "glb",
            "model/gltf+json": "gltf",
            "application/octet-stream": suffix,
        }
        file_type = content_types.get((content_type or "").split(";", 1)[0], suffix)
        if file_type not in _OUTPUT_TYPES:
            raise RuntimeError("Reconstruction provider returned an unsupported mesh format")
        mesh = trimesh.load(
            io.BytesIO(raw_bytes),
            file_type=file_type,
            force="mesh",
        )
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            raise RuntimeError("Reconstruction provider returned an empty mesh")
        exported = mesh.export(file_type="stl")
        if not isinstance(exported, bytes):
            raise RuntimeError("Could not serialize the reconstructed mesh")
        return exported, len(mesh.faces)
