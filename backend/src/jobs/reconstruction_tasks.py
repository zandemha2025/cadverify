"""arq task for image-to-mesh reconstruction with auto-feed to analysis."""
from __future__ import annotations

import io
import logging
import os
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import select

from src.db.engine import get_session_factory
from src.db.models import Job

logger = logging.getLogger("cadverify.jobs.reconstruction_tasks")


async def run_reconstruction_job(ctx: dict, job_ulid: str) -> dict:
    """Reconstruct a 3D mesh from uploaded images and auto-feed to analysis.

    Steps:
        1. Load Job from DB, set running
        2. Read images from blob storage
        3. Select best image, preprocess
        4. Run reconstruction engine
        5. Score mesh confidence
        6. Save mesh to blob storage
        7. Auto-feed into analysis_service.run_analysis()
        8. Write result to Job row
    """
    import trimesh

    from src.reconstruction import preprocessing
    from src.reconstruction.engine import ReconstructParams
    from src.reconstruction.scoring import (
        compute_reconstruction_confidence,
        confidence_level,
        confidence_message,
    )
    from src.services import reconstruction_service

    session_factory = get_session_factory()

    async with session_factory() as session:
        # 1. Load job
        job = (
            await session.execute(select(Job).where(Job.ulid == job_ulid))
        ).scalars().first()
        if job is None:
            logger.error("Reconstruction job %s not found", job_ulid)
            return {"error": "job_not_found"}

        # Set running
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await session.commit()

        try:
            # 2. Read images from blob storage
            from src.services.reconstruction_service import RECON_BLOB_DIR
            input_dir = os.path.join(RECON_BLOB_DIR, job_ulid, "input")

            images_with_types: list[tuple[bytes, str]] = []
            if os.path.isdir(input_dir):
                ext_to_ct = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
                for fname in sorted(os.listdir(input_dir)):
                    ext = fname.rsplit(".", 1)[-1].lower()
                    content_type = ext_to_ct.get(ext, "image/jpeg")
                    with open(os.path.join(input_dir, fname), "rb") as f:
                        images_with_types.append((f.read(), content_type))

            if not images_with_types:
                raise RuntimeError(f"No images found in {input_dir}")

            # 3. Select best image and preprocess
            best_idx = preprocessing.select_best_image(images_with_types)
            best_bytes, best_ct = images_with_types[best_idx]
            processed_image, _meta = preprocessing.preprocess_image(best_bytes, best_ct)

            # Convert PIL Image to bytes for engine
            img_buf = io.BytesIO()
            processed_image.save(img_buf, format="PNG")
            preprocessed_bytes = img_buf.getvalue()

            # 4. Get engine and reconstruct
            engine = reconstruction_service.get_reconstruction_engine()
            result = await engine.reconstruct(preprocessed_bytes, ReconstructParams())

            # 5. Load mesh and compute confidence
            mesh = trimesh.load(io.BytesIO(result.mesh_bytes), file_type="stl")
            score = compute_reconstruction_confidence(mesh)
            level = confidence_level(score)
            message = confidence_message(level)

            # 6. Save mesh to blob storage
            await reconstruction_service.save_reconstruction_mesh(
                job_ulid, result.mesh_bytes
            )

            # 7. Auto-feed to analysis pipeline
            analysis_ulid = None
            analysis_url = None
            try:
                from src.auth.require_api_key import AuthedUser
                from src.services import analysis_service

                params = job.params_json or {}
                process_types = params.get("process_types")
                rule_pack_name = params.get("rule_pack")

                # Create a mock AuthedUser from the job owner
                mock_user = AuthedUser(
                    user_id=job.user_id,
                    api_key_id=0,  # System-generated; no real API key
                    key_prefix="system",
                )

                analysis_result = await analysis_service.run_analysis(
                    file_bytes=result.mesh_bytes,
                    filename=f"reconstructed_{job_ulid}.stl",
                    processes=process_types,
                    rule_pack=rule_pack_name,
                    user=mock_user,
                    session=session,
                )

                # Extract analysis ULID from persisted row
                analysis_id = await analysis_service.get_latest_analysis_id(
                    session,
                    job.user_id,
                    analysis_service.compute_mesh_hash(result.mesh_bytes),
                )
                if analysis_id is not None:
                    from src.db.models import Analysis
                    analysis_row = (
                        await session.execute(
                            select(Analysis).where(Analysis.id == analysis_id)
                        )
                    ).scalars().first()
                    if analysis_row:
                        analysis_ulid = analysis_row.ulid
                        analysis_url = f"/api/v1/analyses/{analysis_ulid}"

            except Exception:
                logger.warning(
                    "Auto-feed to analysis failed for job %s: %s",
                    job_ulid,
                    traceback.format_exc(),
                )
                # Non-fatal: reconstruction succeeded even if analysis fails

            # 8. Build result
            result_json = {
                "reconstruction": {
                    "confidence_score": score,
                    "confidence_level": level,
                    "confidence_message": message,
                    "face_count": result.face_count,
                    "mesh_url": f"/api/v1/reconstructions/{job_ulid}/mesh.stl",
                    "duration_ms": result.duration_ms,
                    "method": result.method,
                },
                "analysis_id": analysis_ulid,
                "analysis_url": analysis_url,
            }

            job.status = "done"
            job.result_json = result_json
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

            logger.info(
                "Reconstruction job %s completed: confidence=%.3f method=%s analysis=%s",
                job_ulid, score, result.method, analysis_ulid,
            )
            return result_json

        except Exception as e:
            logger.exception("Reconstruction job %s failed", job_ulid)
            job.status = "failed"
            job.result_json = {"error": str(e)}
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            return {"error": str(e)}
