"""Image preprocessing pipeline for 3D reconstruction.

Validates, cleans, and prepares uploaded images before passing them to a
reconstruction engine.  Steps: validate -> rembg background removal ->
resize & center -> quality assessment.
"""

from __future__ import annotations

import io
import logging
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCEPTED_IMAGE_TYPES: set[str] = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES: int = 20 * 1024 * 1024  # 20 MB
TARGET_SIZE: int = 512  # TripoSR native input resolution
BLUR_THRESHOLD: float = 100.0  # Laplacian variance; below = blurry


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_image(file_bytes: bytes, content_type: str) -> None:
    """Raise ``ValueError`` if the image is not acceptable."""
    if content_type not in ACCEPTED_IMAGE_TYPES:
        raise ValueError(
            f"Unsupported image type '{content_type}'. "
            f"Accepted: {', '.join(sorted(ACCEPTED_IMAGE_TYPES))}"
        )
    if len(file_bytes) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image size {len(file_bytes)} bytes exceeds "
            f"maximum of {MAX_IMAGE_BYTES} bytes ({MAX_IMAGE_BYTES // (1024 * 1024)} MB)"
        )


# ---------------------------------------------------------------------------
# Blur detection
# ---------------------------------------------------------------------------

# 3x3 discrete Laplacian kernel (no OpenCV dependency)
_LAPLACIAN_KERNEL = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)


def detect_blur(image: Image.Image) -> float:
    """Return the Laplacian variance of *image* (higher = sharper)."""
    gray = np.asarray(image.convert("L"), dtype=np.float64)
    from scipy.ndimage import convolve

    laplacian = convolve(gray, _LAPLACIAN_KERNEL)
    return float(np.var(laplacian))


# ---------------------------------------------------------------------------
# Background removal
# ---------------------------------------------------------------------------


def remove_background(image: Image.Image) -> Image.Image:
    """Remove background using rembg and return RGB on white canvas."""
    from rembg import remove

    rgba_result = remove(image, model_name="isnet-general-use")
    # Composite RGBA onto white RGB background
    white_bg = Image.new("RGB", rgba_result.size, (255, 255, 255))
    if rgba_result.mode == "RGBA":
        white_bg.paste(rgba_result, mask=rgba_result.split()[3])
    else:
        white_bg = rgba_result.convert("RGB")
    return white_bg


# ---------------------------------------------------------------------------
# Resize & center
# ---------------------------------------------------------------------------


def resize_and_center(
    image: Image.Image, target_size: int = TARGET_SIZE
) -> Image.Image:
    """Resize *image* to fit within *target_size* px, centered on white."""
    w, h = image.size
    scale = target_size / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = image.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_size, target_size), (255, 255, 255))
    offset_x = (target_size - new_w) // 2
    offset_y = (target_size - new_h) // 2
    canvas.paste(resized, (offset_x, offset_y))
    return canvas


# ---------------------------------------------------------------------------
# Combined pipeline
# ---------------------------------------------------------------------------


def preprocess_image(
    file_bytes: bytes, content_type: str = "image/jpeg"
) -> tuple[Image.Image, dict]:
    """Full preprocessing pipeline: validate, analyse, clean, resize.

    Returns:
        Tuple of (processed PIL Image, metadata dict).
    """
    validate_image(file_bytes, content_type)

    image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    original_size = image.size

    blur_score = detect_blur(image)
    warning: Optional[str] = (
        "Image may be too blurry" if blur_score < BLUR_THRESHOLD else None
    )

    image = remove_background(image)
    image = resize_and_center(image)

    metadata = {
        "blur_score": blur_score,
        "original_size": original_size,
        "warning": warning,
    }
    return image, metadata


# ---------------------------------------------------------------------------
# Best-image selection
# ---------------------------------------------------------------------------


def select_best_image(images: list[tuple[bytes, str]]) -> int:
    """Return the index of the best image from a set of candidates.

    Scoring: 60% normalised resolution + 40% normalised blur score.
    """
    if not images:
        raise ValueError("At least one image is required")

    scores: list[tuple[int, float]] = []  # (resolution, blur_score)
    for file_bytes, content_type in images:
        validate_image(file_bytes, content_type)
        img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        w, h = img.size
        resolution = w * h
        blur = detect_blur(img)
        scores.append((resolution, blur))

    resolutions = [s[0] for s in scores]
    blurs = [s[1] for s in scores]

    max_res = max(resolutions) or 1
    max_blur = max(blurs) or 1.0

    composites = [
        0.6 * (r / max_res) + 0.4 * (b / max_blur)
        for r, b in zip(resolutions, blurs)
    ]
    return int(np.argmax(composites))
