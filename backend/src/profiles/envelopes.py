"""One build envelope per process, shared by the DFM check and the price.

``COMMON_ENVELOPE_MM`` is the build size ScaleCAD assumes for a process when no
machine is named: the price nests parts in it and won't price a part that
doesn't fit it, and the DFM build-volume check warns above it. It is a typical
machine, not a limit of the process: a part bigger than it is checked against
the machines a shop declares ("too big for your X: needs N, has M"), and only a
part bigger than every machine ScaleCAD knows for the process
(``known_envelopes``: the common size and the catalog's machines) is an error.
"""
from __future__ import annotations

from src.analysis.models import ProcessType as PT

COMMON_ENVELOPE_MM: dict[PT, tuple[float, float, float]] = {
    # A mid-format printer (e.g. Prusa XL 360 x 360 x 360, Creality K2 Plus 350 x 350 x 350).
    # The FDM check used it before this table, and the trap corpus is built on it: a 299 mm block
    # fits, a 300.1 x 290 x 300 part fits turned. The price nests on it too.
    PT.FDM: (300, 300, 350),
    PT.SLA: (145, 145, 185),
    PT.DLP: (192, 120, 245),
    PT.SLS: (340, 340, 600),
    PT.MJF: (380, 284, 380),
    PT.DMLS: (250, 250, 325),
    PT.SLM: (250, 250, 325),
    PT.EBM: (350, 380, 380),
    PT.BINDER_JET: (400, 250, 250),
    PT.DED: (1500, 1500, 1500),
    PT.WAAM: (5000, 3000, 3000),
    PT.CNC_3AXIS: (762, 406, 508),
    PT.CNC_5AXIS: (500, 450, 400),
    PT.CNC_TURNING: (254, 254, 533),   # (swing Ø, swing Ø, between centers)
    PT.WIRE_EDM: (600, 400, 350),
}


def common_envelope(process: PT) -> tuple[float, float, float]:
    return COMMON_ENVELOPE_MM[process]  # already a tuple (tuple() of it was the same object)


def known_envelopes(process: PT) -> list[tuple[str, tuple[float, float, float]]]:
    """``(name, work area)`` for the common size and every catalog machine of the process."""
    from src.profiles.database import MACHINES

    cx, cy, cz = COMMON_ENVELOPE_MM[process]
    out: list[tuple[str, tuple[float, float, float]]] = [("common", (float(cx), float(cy), float(cz)))]
    for m in MACHINES:
        if m.process_type == process and m.build_volume and len(m.build_volume) == 3:
            bx, by, bz = m.build_volume
            env = (float(bx), float(by), float(bz))
            if all(env != e for _, e in out):
                out.append((m.name, env))
    return out
