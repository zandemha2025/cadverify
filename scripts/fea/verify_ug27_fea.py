#!/usr/bin/env python3
"""Independent FEA verification of the UG-27 pressure screen.

Solves three pressurized open-ended cylinders (t/R = 0.05, 0.10, 0.25) with
scikit-fem — an independent open-source finite-element library (its own mesh,
assembly, solver) — using the standard axisymmetric linear-elastic weak form
written for this verification:

    a(u, v) = ∫ 2πr ε(v)ᵀ D ε(u) dr dz,
    ε = [εrr, εzz, εθθ, γrz]ᵀ,  εθθ = u_r / r,
    L(v)   = ∫ 2πr (P v_r) ds  on the bore (traction +P r̂),

and compares, per geometry:

  1. FEA inner-wall hoop stress vs the exact Lamé σθ(a) = P(b²+a²)/(b²−a²)
     (validates the FEA itself: must agree to ~1% or the run is not trusted);
  2. the ASME VIII-1 UG-27(c)(1) working stress the screen encodes —
     rearranged from t = P·R/(S·E − 0.6P) with E = 1 (joint efficiency is a
     weld matter, not a membrane-stress matter) to S_w = P(R/t + 0.3) — vs
     the FEA through-wall membrane (average) hoop stress.

Output: an agreement table; the published tolerance lives in
docs/pressure-screen-fea-verification.md next to this script's committed
output. Exits nonzero when the FEA-vs-Lamé self-check exceeds 2% (a mesh or
formulation problem — never silently published).

Usage:  python3 scripts/fea/verify_ug27_fea.py [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np

E_MPA = 200_000.0     # steel modulus — the stress of a traction-loaded linear
NU = 0.3              # elastic part is load-driven, not stiffness-driven
P_MPA = 10.0          # internal pressure, all three runs

# (label, inner radius a mm, wall t mm): t/R spans thin to well inside UG-27's
# t <= 0.5R validity domain.
GEOMETRIES = [
    ("thin",   40.0,  2.0),   # t/R = 0.05
    ("at_010", 40.0,  4.0),   # t/R = 0.10
    ("thick",  40.0, 10.0),   # t/R = 0.25
]


def lame_hoop_inner(p: float, a: float, b: float) -> float:
    return p * (b * b + a * a) / (b * b - a * a)


def lame_hoop_membrane(p: float, a: float, b: float) -> float:
    """Through-wall average of the Lamé σθ (what a thin-shell formula means
    by hoop stress): P·a/t exactly (equilibrium)."""
    return p * a / (b - a)


def ug27_working_stress(p: float, r: float, t: float) -> float:
    """The stress at which UG-27(c)(1) accepts wall t (E = 1): rearranged from
    t = P·R/(S·E − 0.6P)."""
    return p * (r / t + 0.3)


def solve_cylinder(a: float, b: float, nr: int = 160, nz: int = 20,
                   p: float = P_MPA) -> dict:
    """Solve the open-ended pressurized cylinder; return hoop stresses at the
    inner wall and through-wall membrane, both at mid-length."""
    from skfem import (
        BilinearForm, ElementQuad1, ElementVector, LinearForm, MeshQuad,
    )
    from skfem.helpers import ddot, eye
    from skfem.assembly import Basis
    from skfem.utils import solve

    length = 60.0
    mesh = MeshQuad.init_tensor(np.linspace(a, b, nr), np.linspace(0.0, length, nz))
    mesh = mesh.with_boundaries({
        "bore": lambda x: x[0] < a + 1e-9,        # r = a (inner surface)
        "z0": lambda x: x[1] < 1e-9,              # z = 0 (axial restraint plane)
    })
    elem = ElementVector(ElementQuad1())
    basis = Basis(mesh, elem)

    lame_d = E_MPA / ((1.0 + NU) * (1.0 - 2.0 * NU)) * np.array([
        [1.0 - NU, NU, NU, 0.0],
        [NU, 1.0 - NU, NU, 0.0],
        [NU, NU, 1.0 - NU, 0.0],
        [0.0, 0.0, 0.0, (1.0 - 2.0 * NU) / 2.0],
    ])

    @BilinearForm
    def a_form(u, v, w):
        r = w.x[0]
        e_u = np.stack([
            u.grad[0, 0], u.grad[1, 1], u[0] / r,
            u.grad[0, 1] + u.grad[1, 0],
        ])
        e_v = np.stack([
            v.grad[0, 0], v.grad[1, 1], v[0] / r,
            v.grad[0, 1] + v.grad[1, 0],
        ])
        # ε(v)ᵀ D ε(u), weighted by 2πr (the axisymmetric ring volume)
        return 2.0 * np.pi * r * np.einsum(
            "i...,ij,j...->...", e_v, lame_d, e_u)

    @LinearForm
    def l_form(v, w):
        # Pressure traction +P r̂ on the bore; 2πr from the ring surface.
        return 2.0 * np.pi * w.x[0] * p * v[0]

    A = a_form.assemble(basis)
    # Pressure traction on the bore surface (r = a).
    b_inner = l_form.assemble(basis.boundary("bore"))
    # Open ends: suppress rigid axial motion only, at z = 0 — the uz dofs of
    # the nodes on that plane. Radially the wall stays free.
    bottom_nodes = mesh.nodes_satisfying(lambda x: x[1] < 1e-9)
    fixed_dofs = np.asarray(basis.nodal_dofs[1, bottom_nodes]).reshape(-1)

    from scipy.sparse.linalg import spsolve

    x = np.zeros(basis.N)
    free = np.setdiff1d(np.arange(basis.N), fixed_dofs)
    x[free] = spsolve(A[free][:, free], b_inner[free])

    # Post-process: hoop stress from the strain field, projected through the
    # element quadrature onto probe values. For a uniform (in z) solution the
    # mid-length value equals the analytic 1D field; evaluate σθ via the
    # weak-form strain at quadrature points of the innermost element column.
    # Simpler and exact for this problem: σθ(r) follows from the FEA radial
    # displacement at the two boundaries through Lamé's u_r relation? No —
    # independence demands stress from the FEA itself:
    uh = basis.interpolate(x)

    # Inner-wall σθ: evaluate the strain at the inner boundary quadrature
    # points via a boundary integral of σθ over the bore surface (mid-length
    # slice): numerically integrate σθ(a, z) over the bore at mid length.
    # The solution is z-invariant away from the free end; use the probe
    # machinery of the scalar basis instead: project σθ onto a scalar basis.
    from skfem import ElementQuad1 as _EQ1

    scalar_basis = Basis(mesh, _EQ1())

    @LinearForm
    def hoop_form(v, w):
        r = w.x[0]
        e_u = np.stack([
            uh.grad[0, 0], uh.grad[1, 1], uh[0] / r,
            uh.grad[0, 1] + uh.grad[1, 0],
        ])
        sigma = np.einsum("ij,j...->i...", lame_d, e_u)
        return sigma[2] * v

    from skfem import BilinearForm as _BF

    @_BF
    def mass_form(u, v, w):
        return u * v

    M = mass_form.assemble(scalar_basis)
    rhs = hoop_form.assemble(scalar_basis, uh=uh)
    sigma_theta = spsolve(M, rhs)

    # Probe σθ near the inner wall at mid-length (a + half-element, z = L/2).
    dr = (b - a) / (nr - 1)
    probe_inner = scalar_basis.probes(np.array([[a + 0.51 * dr], [length / 2.0]]))
    s_inner = float(np.asarray(probe_inner @ sigma_theta).reshape(-1)[0])

    # Membrane: average σθ over the wall at mid-length (sampled).
    rs = a + dr + np.linspace(0.0, (b - a) - 2 * dr, 400)
    pts = np.vstack((rs, np.full(rs.shape, length / 2.0)))
    s_wall = np.asarray(scalar_basis.probes(pts) @ sigma_theta)
    membrane = float(np.mean(s_wall))

    # FEA self-check vs Lamé at the inner wall.
    return {
        "a_mm": a, "b_mm": b, "t_mm": b - a,
        "fea_inner_hoop_mpa": s_inner,
        "fea_membrane_hoop_mpa": membrane,
        "lame_inner_mpa": lame_hoop_inner(p, a, b),
        "lame_membrane_mpa": lame_hoop_membrane(p, a, b),
        "ug27_working_mpa": ug27_working_stress(p, a + (b - a) / 2.0, b - a),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    rows = []
    ok = True
    print(f"scikit-fem UG-27 verification  (P = {P_MPA} MPa, E = {E_MPA / 1e3} GPa, nu = {NU})")
    for label, a, t in GEOMETRIES:
        res = solve_cylinder(a, a + t)
        lame_err = 100.0 * (res["fea_inner_hoop_mpa"] - res["lame_inner_mpa"]) / res["lame_inner_mpa"]
        memb_err = 100.0 * (res["fea_membrane_hoop_mpa"] - res["lame_membrane_mpa"]) / res["lame_membrane_mpa"]
        ug27_err = 100.0 * (res["ug27_working_mpa"] - res["fea_membrane_hoop_mpa"]) / res["fea_membrane_hoop_mpa"]
        if abs(lame_err) > 2.0:
            ok = False
        rows.append({"label": label, **res,
                     "fea_vs_lame_inner_pct": lame_err,
                     "fea_vs_lame_membrane_pct": memb_err,
                     "ug27_vs_fea_membrane_pct": ug27_err})
        print(f"[{label:>7}] t/R={t/a:.2f}  "
              f"FEA σθ(inner)={res['fea_inner_hoop_mpa']:8.2f}  Lamé={res['lame_inner_mpa']:8.2f}  "
              f"Δ{lame_err:+6.2f}%  |  membrane: FEA={res['fea_membrane_hoop_mpa']:7.2f}  "
              f"Lamé P·a/t={res['lame_membrane_mpa']:7.2f} Δ{memb_err:+6.2f}%  |  "
              f"UG-27 working={res['ug27_working_mpa']:7.2f}  Δ vs FEA{ug27_err:+6.2f}%")
    if not ok:
        print("FEA vs Lamé self-check exceeded 2% — mesh/formulation problem; not published.",
              file=sys.stderr)
        return 1
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(rows, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
