"""SAM-3D semantic segmentation pipeline.

Multi-view rendering -> SAM-2 automatic mask generation -> 2D-to-3D mask
lifting -> manufacturing feature classifier.

All heavy dependencies (torch, pyrender, segment-anything) are optional.
When unavailable the pipeline gracefully returns empty results.
"""

from src.segmentation.sam3d.pipeline import is_sam3d_available, segment_sam3d

__all__ = ["is_sam3d_available", "segment_sam3d"]
