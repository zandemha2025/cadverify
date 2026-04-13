"""SAM-2 backbone wrapper for automatic mask generation.

Wraps the ``segment-anything-2`` model behind a thin interface.  When the
library or model weights are not available the wrapper returns empty mask
lists so the rest of the pipeline degrades cleanly.
"""

from __future__ import annotations

import numpy as np

from src.segmentation.sam3d.types import Mask

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------
_SAM2_AVAILABLE = False
try:
    from segment_anything_2.automatic_mask_generator import (  # type: ignore[import-untyped]
        SamAutomaticMaskGenerator,
    )
    from segment_anything_2.build_sam import build_sam2  # type: ignore[import-untyped]

    _SAM2_AVAILABLE = True
except ImportError:
    pass


def is_backbone_available() -> bool:
    """Return True if the SAM-2 library is importable."""
    return _SAM2_AVAILABLE


class SAM2Backbone:
    """Thin wrapper around SAM-2 automatic mask generation.

    Instantiation is cheap when the model is not loaded — ``generate_masks``
    simply returns ``[]``.  Call ``load()`` with a checkpoint path to activate
    the real model.
    """

    def __init__(self) -> None:
        self._generator: object | None = None
        self._loaded = False

    def load(self, checkpoint_path: str) -> None:
        """Load model weights from *checkpoint_path*.

        No-ops silently if the SAM-2 library is not installed.
        """
        if not _SAM2_AVAILABLE:
            return

        try:
            model = build_sam2(checkpoint_path)  # type: ignore[arg-type]
            self._generator = SamAutomaticMaskGenerator(model)  # type: ignore[arg-type]
            self._loaded = True
        except Exception:
            self._generator = None
            self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def generate_masks(self, image: np.ndarray) -> list[Mask]:
        """Run automatic mask generation on an RGB image.

        Args:
            image: (H, W, 3) uint8 array.

        Returns:
            List of :class:`Mask` instances, empty when the backbone is
            unavailable or the model has not been loaded.
        """
        if self._generator is None:
            return []

        if image is None or image.size == 0:
            return []

        try:
            raw_masks = self._generator.generate(image)  # type: ignore[union-attr]
        except Exception:
            return []

        masks: list[Mask] = []
        for entry in raw_masks:
            binary = np.asarray(entry["segmentation"], dtype=bool)
            confidence = float(entry.get("predicted_iou", 0.0))
            masks.append(Mask(binary_mask=binary, confidence=confidence))

        return masks
