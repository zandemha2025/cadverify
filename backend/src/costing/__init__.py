"""CadVerify V0 decision layer — explainable should-cost, lead time, quantity
crossover, and make-vs-buy direction on top of the existing DFM engine.

Public surface:
    estimate_decision(result, mesh, features, options) -> DecisionReport
    EstimateOptions, DecisionReport
    render_text(report), report_to_dict(report)
    RATE_CARD_V0

The layer is read-only: it consumes AnalysisResult + mesh + features and never
mutates the engine, the registry, or `result`. It emits dollars with drivers or
nothing — the legacy toy `estimated_cost_factor` is never surfaced.
"""

from src.costing.estimate import EstimateOptions, DecisionReport, estimate_decision
from src.costing.report import render_text, report_to_dict
from src.costing.rates import RATE_CARD_V0
from src.costing.shop_profile import (
    ShopProfile, save_profile, load_profile, list_profiles, resolve_shop,
    DEFAULT_STORE_DIR,
)
from src.costing.confidence import ConfidenceInterval, confidence_interval
from src.costing.ensemble import (
    ensemble_estimate, combine_inverse_variance, ensemble_enabled,
    EnsembleResult, EnsembleBand, UNCERTAIN_COEFFICIENTS, COST_ENSEMBLE_ENABLED,
)
from src.costing.groundtruth import (
    GroundTruthRecord, load_records, save_records, add_record,
    split_records, tune, evaluate, run_loop, build_report,
    Calibration, ResidualModel, EngineCostCache, make_standin_record,
)

__all__ = [
    "estimate_decision",
    "EstimateOptions",
    "DecisionReport",
    "render_text",
    "report_to_dict",
    "RATE_CARD_V0",
    # per-shop calibration
    "ShopProfile",
    "save_profile",
    "load_profile",
    "list_profiles",
    "resolve_shop",
    "DEFAULT_STORE_DIR",
    # per-estimate confidence interval
    "ConfidenceInterval",
    "confidence_interval",
    # assumption-ensemble uncertainty (Moat P0)
    "ensemble_estimate",
    "combine_inverse_variance",
    "ensemble_enabled",
    "EnsembleResult",
    "EnsembleBand",
    "UNCERTAIN_COEFFICIENTS",
    "COST_ENSEMBLE_ENABLED",
    # ground-truth accuracy loop (bucket #4 measurement)
    "GroundTruthRecord",
    "load_records",
    "save_records",
    "add_record",
    "split_records",
    "tune",
    "evaluate",
    "run_loop",
    "build_report",
    "Calibration",
    "ResidualModel",
    "EngineCostCache",
    "make_standin_record",
]
