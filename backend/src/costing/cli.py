"""V0 demo CLI (spec §11).

    python -m src.costing.cli <part.stl> [--qty 50,5000] [--material-class polymer]
            [--region US] [--labor-rate 35] [--set machine_rate.SLS=25]
            [--tooling INJECTION_MOLDING=50000] [--strict-dfm] [--json out.json]

Runs the canonical engine sequence, builds EstimateOptions from flags (flags ->
USER provenance; absent -> DEFAULT), calls estimate_decision, prints the
decision card, and writes the JSON sidecar next to the part (or --json path).

Zero network calls. Exit 0 on OK and on GEOMETRY_INVALID (prints the card,
does not crash).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings


def _run_engine(path: str):
    """Canonical engine sequence (mirrors routes.py::validate_public)."""
    import trimesh
    import src.analysis.processes  # noqa: F401  populate registry
    from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
    from src.analysis.context import GeometryContext
    from src.analysis.features import detect_all as detect_features
    from src.matcher.profile_matcher import rank_processes, score_process
    from src.analysis.processes.base import get_analyzer
    from src.analysis.processes import base as pbase
    from src.analysis.models import AnalysisResult

    mesh = trimesh.load(path, force="mesh")
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    # ctx.mesh == mesh unless build() decimated an oversize mesh; detect on
    # ctx.mesh so feature indices align with the context per-face arrays.
    ctx.features = detect_features(ctx.mesh)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(
        filename=os.path.basename(path), file_type="stl", geometry=geometry,
        segments=ctx.segments, universal_issues=universal, process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx.features


def _parse_overrides(args) -> dict:
    overrides: dict = {}
    if args.labor_rate is not None:
        overrides["labor_rate"] = args.labor_rate
    if args.margin is not None:
        overrides["margin"] = args.margin
    for s in (args.set or []):
        k, _, v = s.partition("=")
        overrides[k.strip()] = float(v)
    for t in (args.tooling or []):
        proc, _, v = t.partition("=")
        overrides[f"tooling.{proc.strip()}"] = float(v)
    return overrides


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="src.costing.cli",
                                     description="CadVerify V0 decision layer")
    parser.add_argument("part", help="path to part .stl")
    parser.add_argument("--qty", default="50,5000", help="comma list, e.g. 50,5000")
    parser.add_argument("--material-class", default=None,
                        help="polymer|aluminum|steel|stainless|titanium (DEFAULT polymer)")
    parser.add_argument("--region", default=None, help="US|EU|MX|CN|IN|SA (selects 3 region vectors)")
    parser.add_argument("--shop", default=None,
                        help="per-shop calibration: a stored profile NAME or a path to a profile .json")
    parser.add_argument("--cavities", type=int, default=None,
                        help="formative tooling cavity count (DEFAULT 1)")
    parser.add_argument("--complexity", default=None,
                        help="simple|moderate|complex|very_complex (DEFAULT moderate)")
    parser.add_argument("--labor-rate", type=float, default=None)
    parser.add_argument("--margin", type=float, default=None)
    parser.add_argument("--set", action="append", default=[],
                        help="per-process override, e.g. machine_rate.SLS=25")
    parser.add_argument("--tooling", action="append", default=[],
                        help="flat tooling override, e.g. INJECTION_MOLDING=50000")
    parser.add_argument("--strict-dfm", action="store_true",
                        help="drop verdict=='fail' processes (literal spec §5.3)")
    parser.add_argument("--json", default=None, help="JSON sidecar output path")
    parser.add_argument("--quiet", action="store_true", help="suppress engine warnings")
    args = parser.parse_args(argv)

    if args.quiet:
        warnings.simplefilter("ignore")

    from src.costing import estimate_decision, EstimateOptions, render_text, report_to_dict

    t0 = time.time()
    result, mesh, features = _run_engine(args.part)

    quantities = [int(x) for x in args.qty.split(",") if x.strip()]
    options = EstimateOptions(
        quantities=quantities,
        material_class=(args.material_class or "polymer"),
        material_class_is_user=args.material_class is not None,
        region=(args.region or "US"),
        region_is_user=args.region is not None,
        shop=args.shop,
        rate_overrides=_parse_overrides(args),
        strict_dfm=args.strict_dfm,
        n_cavities=(args.cavities if args.cavities is not None else 1),
        n_cavities_is_user=args.cavities is not None,
        complexity=(args.complexity or "moderate"),
        complexity_is_user=args.complexity is not None,
    )
    report = estimate_decision(result, mesh, features, options)
    elapsed = time.time() - t0

    print(render_text(report))
    print(f"\n[wall-clock {elapsed:.2f}s · IP-local, zero network calls]")

    out_path = args.json or (os.path.splitext(args.part)[0] + ".decision.json")
    with open(out_path, "w") as f:
        json.dump(report_to_dict(report), f, indent=2)
    print(f"[JSON sidecar → {out_path}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
