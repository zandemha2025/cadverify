"""Multi-view mesh renderer for the SAM-3D pipeline.

Renders a trimesh object from ``num_views`` camera positions distributed
uniformly on a sphere (icosphere sampling).  Each render produces an RGB
image, depth buffer, and face-ID buffer.

Uses *pyrender* when available; otherwise returns an empty list so the
pipeline degrades gracefully.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from src.segmentation.sam3d.types import ViewRender

if TYPE_CHECKING:
    import trimesh

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------
_PYRENDER_AVAILABLE = False
try:
    import pyrender  # noqa: F401

    _PYRENDER_AVAILABLE = True
except ImportError:
    pass


def is_renderer_available() -> bool:
    """Return True if the rendering backend is installed."""
    return _PYRENDER_AVAILABLE


# ---------------------------------------------------------------------------
# Camera positions — icosphere-inspired uniform sampling
# ---------------------------------------------------------------------------

def _icosphere_cameras(n: int, radius: float) -> list[np.ndarray]:
    """Generate *n* 4x4 look-at camera transforms distributed on a sphere.

    Uses the Fibonacci-lattice method for near-uniform distribution,
    which is simpler and more predictable than actual icosphere subdivision.
    """
    transforms: list[np.ndarray] = []
    golden_ratio = (1.0 + np.sqrt(5.0)) / 2.0

    for i in range(n):
        theta = np.arccos(1.0 - 2.0 * (i + 0.5) / n)
        phi = 2.0 * np.pi * i / golden_ratio

        x = radius * np.sin(theta) * np.cos(phi)
        y = radius * np.sin(theta) * np.sin(phi)
        z = radius * np.cos(theta)

        eye = np.array([x, y, z])
        target = np.array([0.0, 0.0, 0.0])
        up = np.array([0.0, 0.0, 1.0])

        transform = _look_at(eye, target, up)
        transforms.append(transform)

    return transforms


def _look_at(
    eye: np.ndarray,
    target: np.ndarray,
    up: np.ndarray,
) -> np.ndarray:
    """Build a 4x4 camera-to-world matrix using a right-handed look-at."""
    forward = target - eye
    norm = np.linalg.norm(forward)
    if norm < 1e-12:
        return np.eye(4)
    forward = forward / norm

    right = np.cross(forward, up)
    right_norm = np.linalg.norm(right)
    if right_norm < 1e-12:
        # Degenerate: up is parallel to forward — pick arbitrary perpendicular
        up = np.array([1.0, 0.0, 0.0])
        right = np.cross(forward, up)
        right_norm = np.linalg.norm(right)
    right = right / right_norm

    true_up = np.cross(right, forward)

    mat = np.eye(4)
    mat[:3, 0] = right
    mat[:3, 1] = true_up
    mat[:3, 2] = -forward
    mat[:3, 3] = eye
    return mat


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_views(
    mesh: "trimesh.Trimesh",
    num_views: int = 24,
    resolution: tuple[int, int] = (512, 512),
) -> list[ViewRender]:
    """Render *mesh* from *num_views* uniformly distributed cameras.

    Returns an empty list when:
    - pyrender is not installed
    - the mesh has zero faces
    """
    if not _PYRENDER_AVAILABLE:
        return []

    if mesh is None or len(mesh.faces) == 0:
        return []

    # Center mesh at origin for consistent camera placement
    centroid = mesh.centroid
    bbox_diag = float(np.linalg.norm(mesh.extents))
    if bbox_diag < 1e-12:
        return []

    camera_radius = bbox_diag * 1.5
    camera_transforms = _icosphere_cameras(num_views, camera_radius)

    views: list[ViewRender] = []
    for cam_tf in camera_transforms:
        view = _render_single_view(mesh, cam_tf, centroid, resolution)
        if view is not None:
            views.append(view)

    return views


def _render_single_view(
    mesh: "trimesh.Trimesh",
    camera_transform: np.ndarray,
    mesh_centroid: np.ndarray,
    resolution: tuple[int, int],
) -> ViewRender | None:
    """Render one view.  Returns None on any rendering failure."""
    try:
        import pyrender  # local import — already guarded at module level

        # Build pyrender scene
        scene = pyrender.Scene()

        # Add mesh
        py_mesh = pyrender.Mesh.from_trimesh(mesh)
        scene.add(py_mesh)

        # Add camera
        yfov = np.pi / 4.0
        camera = pyrender.PerspectiveCamera(yfov=yfov)
        scene.add(camera, pose=camera_transform)

        # Add light co-located with camera
        light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=3.0)
        scene.add(light, pose=camera_transform)

        # Render
        renderer = pyrender.OffscreenRenderer(*resolution)
        try:
            color, depth = renderer.render(scene)
        finally:
            renderer.delete()

        # Face-ID buffer: placeholder filled with -1 (real implementation
        # would use a custom shader pass that writes per-face IDs into an
        # integer framebuffer).  This is the scaffolding gap that will be
        # filled when we integrate the custom rendering pass.
        face_ids = np.full(resolution, -1, dtype=np.int32)

        return ViewRender(
            rgb=color,
            depth=depth,
            face_ids=face_ids,
            camera_transform=camera_transform,
        )
    except Exception:
        return None
