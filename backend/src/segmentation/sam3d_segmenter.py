"""Legacy entry point -- delegates to the sam3d package.

The old DBSCAN-based placeholder has been replaced by a modular pipeline:
multi-view rendering -> SAM-2 mask generation -> 2D-to-3D lifting ->
manufacturing feature classification.

Import from ``src.segmentation.sam3d`` directly for new code.
"""

from src.segmentation.sam3d import is_sam3d_available, segment_sam3d

__all__ = ["is_sam3d_available", "segment_sam3d"]
