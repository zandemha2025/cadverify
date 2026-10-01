"""Independent constructive samples for the continuous cylinder-fit solver.

Run from backend: PYTHONPATH=. .venv/bin/python ../outputs/production-audit-20260929/190-cylinder-oracle.py.
"""
import json
import time
from pathlib import Path

import numpy as np
from src.analysis.context import fitting_box_dimensions

rng = np.random.default_rng(190)
start = time.perf_counter()
positive = negative = 0
for length, diameter in ((8, 220), (200, 40), (60, 60), (.008, .22), (8000, 220000)):
    directions = np.vstack((np.eye(3), (1, 1, 1), (1, 1, 0), rng.normal(size=(60, 3))))
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    for direction in directions:
        # The full analytic cylinder fits by construction, independently of the solver.
        envelope = length * np.abs(direction) + diameter * np.sqrt(np.maximum(0, 1 - direction**2))
        envelope *= 1.00001
        placement = fitting_box_dimensions((diameter, diameter, length), envelope, (length, diameter))
        assert placement is not None, (length, diameter, envelope)
        assert np.all(np.asarray(placement) <= envelope + 1e-9)
        positive += 1
        # Every cylinder projection spans at least its shorter axial/radial dimension.
        assert fitting_box_dimensions((diameter, diameter, length), (min(length, diameter) * .9,) * 3,
                                      (length, diameter)) is None
        negative += 1
proof = {"seed": 190, "constructive_positive_cases": positive,
         "proven_negative_cases": negative, "seconds": time.perf_counter() - start,
         "scope": "Analytic cylinder placements across orientations and scales; no general-shape minimum-cylinder claim."}
Path(__file__).with_suffix(".json").write_text(json.dumps(proof, indent=2) + "\n")
print(json.dumps(proof, indent=2))
