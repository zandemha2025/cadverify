"""Cycle 4 EVAL + SIMILARITY harness (spec §6).

Measures the DFM engine's *routing accuracy* against human ground-truth labels and
provides a k-NN "resembles these labeled parts" similarity lookup as explainable
evidence.

Hard honesty rules baked into this package:

* **No auto-labeling.** The ground-truth ``label`` is human-applied only. This
  package never writes a label; it only *reads* ``data/labels.jsonl`` and compares
  the engine's pick against it.
* **Smoke seed is quarantined.** ``data/labels.seed.jsonl`` (labeler
  ``SMOKE_SEED``) exists only to exercise the pipeline end-to-end. It is *never*
  counted toward the human-label gate and never mixed into real metrics.
* **Real metrics are gated.** Until there are at least ``MIN_HUMAN_LABELS`` (30)
  human labels in the 5 manufacturable classes, the harness runs end-to-end but
  prints an ``INSUFFICIENT HUMAN LABELS`` banner and marks every number
  PROVISIONAL / SMOKE.

Public surface re-exported here is the single source of truth other modules and
the frontend mirror against.
"""

from __future__ import annotations

from src.eval.ontology import FAMILY_OF, LABELS, MANUFACTURABLE, family_of

__all__ = ["FAMILY_OF", "LABELS", "MANUFACTURABLE", "family_of"]
