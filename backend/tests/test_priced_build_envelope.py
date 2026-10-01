"""Costed builds must fit the very machine whose capacity/time is priced."""
from dataclasses import asdict, replace
from math import pi

import pytest
import trimesh

from src.analysis.models import ProcessType as PT
from src.costing import EstimateOptions, estimate_decision
from src.costing.cost_model import _additive_machine, cost_breakdown
from src.costing.drivers import extract_drivers, parts_per_build
from src.costing.makeability import MachineCap, ShopCaps, fit_machine, part_req_from_drivers
from src.costing.rates import build_rate_card
from src.costing.routing import select_material
from tests.test_costing_model import _analyze


def test_envelope_failure_requires_geometric_evidence_and_named_bounds():
    from math import sqrt
    from src.analysis.processes.checks import check_build_volume
    from tests.test_analyzers import _build_ctx

    material = select_material(PT.FDM, "polymer", build_rate_card())
    machine = MachineCap(process="fdm", name="200mm cube", max_workpiece_kg=5,
                         materials=("polymer",), hourly_rate_usd=10,
                         capabilities={"x": 200, "y": 200, "z": 200})
    bar = _build_ctx(trimesh.creation.box(extents=(400, 12, 12)))
    fit = fit_machine(part_req_from_drivers(PT.FDM, extract_drivers(bar.info, bar.mesh, bar.features),
                                            material, "standard"), machine)
    failure = next(f for f in fit.failures if f.gate == "envelope")
    assert failure.axis == "diameter_mm"
    assert failure.need == pytest.approx(400)
    assert failure.have == pytest.approx(sqrt(3)*200, abs=.01)
    assert "diagonal" in failure.human and "not a machine specification" in failure.human

    # The round disk has a proved tilted placement even though its enclosing
    # rectangular box search fails: XYZ = diameter*sqrt(2/3) + height/sqrt(3).
    assert 220*sqrt(2/3) + 8/sqrt(3) < 200
    disk = _build_ctx(trimesh.creation.cylinder(radius=110, height=8, sections=64))
    issues = check_build_volume(disk, (200, 200, 200), PT.FDM)
    assert not any(i.code == "EXCEEDS_BUILD_VOLUME" for i in issues)
    assert any(i.code == "BUILD_ENVELOPE_UNVERIFIED" for i in issues)
    fit = fit_machine(part_req_from_drivers(PT.FDM, extract_drivers(disk.info, disk.mesh, disk.features),
                                            material, "standard"), machine)
    assert not fit.passes
    assert all(f.have is None for f in fit.failures if f.gate == "envelope")

    # A cube's inscribed sphere proves excess independently of its upload axes.
    cube = trimesh.creation.box(extents=(300.1,)*3)
    cube.apply_transform(trimesh.transformations.rotation_matrix(.71, (1, 2, 3)))
    issues = check_build_volume(_build_ctx(cube), (300, 300, 350), PT.FDM)
    assert any(i.code == "EXCEEDS_BUILD_VOLUME" and "minimum width" in i.message for i in issues)


def test_body_diagonal_bar_fit_uses_the_same_height_in_dfm_inventory_and_price():
    import numpy as np
    from math import sqrt
    from src.analysis.context import fitting_box_dimensions
    from src.analysis.models import Severity
    from src.analysis.processes.checks import check_build_volume
    from tests.test_analyzers import _build_ctx

    # Independent eight-corner construction: the 400mm axis points along (1,1,1).
    rotation = np.array(((1/sqrt(2), 1/sqrt(6), 1/sqrt(3)),
                         (-1/sqrt(2), 1/sqrt(6), 1/sqrt(3)),
                         (0, -2/sqrt(6), 1/sqrt(3))))
    corners = trimesh.creation.box(extents=(12, 12, 400)).vertices @ rotation.T
    oracle = np.ptp(corners, axis=0)
    assert np.all(oracle < 250) and 400 > 250 * sqrt(2)
    envelope = (250, 250, 250)
    assert fitting_box_dimensions((12, 12, 400), envelope) == pytest.approx(oracle)
    assert fitting_box_dimensions((12, 12, 400), (200, 200, 200)) is None
    rates = build_rate_card()
    material = select_material(PT.FDM, "polymer", rates)
    machine = MachineCap(process="fdm", name="Body diagonal fixture", max_workpiece_kg=5,
                         materials=("polymer",), hourly_rate_usd=10,
                         capabilities=dict(zip(("x", "y", "z"), envelope)))
    for angle, axis in ((0, (0, 0, 1)), (pi/4, (0, 0, 1)), (.71, (1, 2, 3))):
        mesh = trimesh.creation.box(extents=(400, 12, 12))
        mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, axis))
        ctx = _build_ctx(mesh)
        assert not any(i.severity == Severity.ERROR for i in check_build_volume(ctx, envelope, PT.FDM))
        drivers = extract_drivers(ctx.info, mesh, ctx.features)
        fit = fit_machine(part_req_from_drivers(PT.FDM, drivers, material, "standard"), machine)
        assert fit.passes, fit.failures
        hours, count, source = _additive_machine(PT.FDM, drivers, rates)
        assert count == 1
        assert hours == pytest.approx(57.6/rates.p(PT.FDM, "deposition")
                                     + oracle[2]/rates.p(PT.FDM, "vert"))
        assert "240.738" in source
        assert _additive_machine(PT.FDM, drivers, rates,
                                {**fit.resource_hint, "machine_name": fit.machine})[:2] == (hours, count)


@pytest.mark.parametrize("length,envelope", [(250, (200, 200, 200)), (400, (300, 300, 350))])
def test_diagonal_bar_fit_agrees_in_dfm_owned_machine_and_price(length, envelope):
    from math import sqrt
    from src.analysis.models import Severity
    from src.analysis.processes.checks import check_build_volume
    from tests.test_analyzers import _build_ctx

    # A 45-degree placement is an independent constructive fit proof.
    assert (length + 12) / sqrt(2) < min(envelope[:2])
    rates = build_rate_card()
    material = select_material(PT.FDM, "polymer", rates)
    machine = MachineCap(process="fdm", name="Diagonal fixture", max_workpiece_kg=5,
                         materials=("polymer",), hourly_rate_usd=10,
                         capabilities=dict(zip(("x", "y", "z"), envelope)))
    for angle in (0, pi / 4, .73):
        mesh = trimesh.creation.box(extents=(length, 12, 12))
        mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, (0, 0, 1)))
        ctx = _build_ctx(mesh)
        assert not any(i.severity == Severity.ERROR for i in check_build_volume(ctx, envelope, PT.FDM))
        drivers = extract_drivers(ctx.info, mesh, ctx.features)
        req = part_req_from_drivers(PT.FDM, drivers, material, "standard")
        fit = fit_machine(req, machine)
        assert fit.passes, fit.failures
        override = {**fit.resource_hint, "machine_name": fit.machine}
        hours, count, source = _additive_machine(PT.FDM, drivers, rates, override)
        assert count == 1
        assert hours == pytest.approx(length * 12 * 12 / 1000 / rates.p(PT.FDM, "deposition")
                                     + 12 / rates.p(PT.FDM, "vert"))
        assert "Diagonal fixture" in source


def test_priced_build_fit_controls_all_quantities_overrides_and_owned_machines():
    result, mesh, features = _analyze(trimesh.creation.box(extents=[320] * 3))
    options = EstimateOptions(quantities=[1, 100], material_class="aluminum")
    original = asdict(result)
    report = estimate_decision(result, mesh, features, options)
    assert not any(e["process"] in {"dmls", "slm"} for e in report.estimates)
    assert any("dmls" in n and "250" in n and "withheld" in n for n in report.notes)
    assert asdict(result) == original  # generic DFM evidence is a separate check
    assert all(not row["costed"] for row in report.engine_feasibility
               if row["process"] in {"dmls", "slm"})
    assert report.routing is None or report.routing["recommended_process"] not in {"dmls", "slm"}
    assert report.decision is None or report.decision.make_now_process not in {"dmls", "slm"}

    drivers = extract_drivers(result.geometry, mesh, features)
    rates = build_rate_card()
    material = select_material(PT.DMLS, "aluminum", rates)
    assert parts_per_build(PT.DMLS, (320, 320, 320), rates) == 0
    with pytest.raises(ValueError, match="priced build envelope"):
        cost_breakdown(PT.DMLS, drivers, material, "aluminum", 1, rates, "US")

    large = replace(options, rate_overrides={"build_env_mm.DMLS": (400, 400, 500)})
    larger_report = estimate_decision(result, mesh, features, large)
    assert {e["quantity"] for e in larger_report.estimates if e["process"] == "dmls"} == {1, 100}
    # A fitted declared machine must supply its own XYZ capacity as well as $/hr.
    machine = MachineCap(process="dmls", name="Large test printer", max_workpiece_kg=500,
                         hourly_rate_usd=100, capital_frac=0,
                         materials=("aluminum",), capabilities={"x": 400, "y": 400, "z": 500})
    owned = estimate_decision(result, mesh, features, replace(
        options, inventory=(machine,), shop_caps=ShopCaps(ops={"stress_relief": True})))
    dmls = [e for e in owned.estimates if e["process"] == "dmls"]
    assert len(dmls) == 2
    assert owned.verification["per_route"]["dmls"]["verdict"] == "makeable_with_secondary_op"
    source = next(d["source"] for d in dmls[0]["drivers"] if d["name"] == "machine_cost")
    assert "500mm" in source and "Large test printer" in source

    # A tall fitting orientation must not be priced as an impossible flat build.
    tall_rates = build_rate_card({"build_env_mm.FDM": (100, 100, 400)})
    tall = replace(drivers, bbox_mm=(20, 50, 300), billet_bbox_mm=(20, 50, 300), volume_cm3=300)
    hours, count, source = _additive_machine(PT.FDM, tall, tall_rates)
    assert hours == pytest.approx(300 / tall_rates.p(PT.FDM, "deposition")
                                + 300 / tall_rates.p(PT.FDM, "vert") / count)
    assert "300" in source
    assert parts_per_build(PT.FDM, (150, 150, 150), build_rate_card()) == 1

    # Binder-jet fit and nesting use the same green oversize as material cost.
    green = replace(drivers, bbox_mm=(230, 230, 230), billet_bbox_mm=(230, 230, 230))
    with pytest.raises(ValueError, match="priced build envelope"):
        _additive_machine(PT.BINDER_JET, green, rates)
    zero_shrink = build_rate_card({"shrinkage_linear.BINDER_JET": 0})
    assert _additive_machine(PT.BINDER_JET, green, zero_shrink)[1] >= 1

    green_result, green_mesh, green_features = _analyze(trimesh.creation.box(extents=[230] * 3))
    binder = replace(machine, process="binder_jetting", materials=("stainless",),
                     capabilities={"x": 250, "y": 250, "z": 400})
    green_options = replace(options, material_class="stainless", inventory=(binder,),
                            shop_caps=ShopCaps(ops={"sinter": True}))
    green_report = estimate_decision(green_result, green_mesh, green_features, green_options)
    assert green_report.verification["per_route"]["binder_jetting"]["verdict"] != "makeable_in_house"
    assert any(f["gate"] == "envelope" for f in
               green_report.verification["per_route"]["binder_jetting"]["failures"])

    for invalid in [(), (250, 250), (250, 250, 325, 1), (250, 250, 0)]:
        with pytest.raises(ValueError, match="build_env_mm"):
            build_rate_card({"build_env_mm.DMLS": invalid})


def test_enterprise_binder_green_batch_cost_oracle():
    # cube.step is a 20x15x10 block with a diameter-6 through bore.
    # Use its analytic volume so the oracle is independent of the CAD tessellator.
    result, mesh, features = _analyze(trimesh.creation.box(extents=[20, 15, 10]))
    drivers = replace(extract_drivers(result.geometry, mesh, features),
                      volume_cm3=(20 * 15 * 10 - pi * 3**2 * 10) / 1000)
    rates = build_rate_card()
    estimate = cost_breakdown(PT.BINDER_JET, drivers,
                              select_material(PT.BINDER_JET, "stainless", rates),
                              "stainless", 12000, rates, "US")
    # 18% declared green oversize, 6mm spacing, 12% packing in 400x250x250:
    # floor(3,000,000 / (29.6 * 23.7 * 17.8)) = 240 parts/build.
    assert next(d.value for d in estimate.drivers if d.name == "parts_per_build") == 240
    assert estimate.line_items == pytest.approx({
        "material": 0.1962, "machine": 1.6667, "sinter": 1.5,
        "labor": 0, "amortized_fixed": 0.0729,
    }, abs=0.00005)
    assert round(estimate.unit_cost_usd, 2) == 3.44
    assert round(estimate.unit_cost_usd, 2) * 12000 == 41280
