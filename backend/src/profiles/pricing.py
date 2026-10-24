"""Which material price a process pays: the form it consumes.

A material file lists prices by the form the material is bought in, e.g.
316L at $5/kg as bar, $100/kg as powder and $4/kg as sheet. A laser
powder-bed printer buys powder, a mill buys bar, a press brake buys sheet, so
each process is priced at its own form, never at the first number in the file.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from src.analysis.models import ProcessType
from src.profiles.models import MaterialProfile

PT = ProcessType

_MACHINED = ("wrought", "bar", "rod", "plate")

#: The forms each process consumes, most specific first.
FEEDSTOCK_FORMS: dict[ProcessType, tuple[str, ...]] = {
    PT.FDM: ("filament",),
    PT.SLA: ("resin",),
    PT.DLP: ("resin",),
    PT.SLS: ("powder",),
    PT.MJF: ("powder",),
    PT.DMLS: ("powder",),
    PT.SLM: ("powder",),
    PT.EBM: ("powder",),
    PT.BINDER_JET: ("powder",),
    PT.DED: ("powder",),
    # Wire-arc deposition buys wire. No material file carries a wire price yet,
    # so the alloy's powder price stands in (never its bar price).
    PT.WAAM: ("wire", "powder"),
    PT.CNC_3AXIS: _MACHINED,
    PT.CNC_5AXIS: _MACHINED,
    PT.CNC_TURNING: _MACHINED,
    PT.WIRE_EDM: _MACHINED,
    PT.FORGING: ("bar", "wrought"),
    PT.INJECTION_MOLDING: ("pellet",),
    PT.DIE_CASTING: ("ingot", "cast"),
    PT.SAND_CASTING: ("ingot", "cast"),
    PT.INVESTMENT_CASTING: ("ingot", "cast"),
    PT.SHEET_METAL: ("sheet",),
}

#: Processes that can only be priced at their own form: a metal printer or
#: deposition cell priced at the bar price under-quotes its feedstock 10-20x.
_FORM_REQUIRED = frozenset({PT.DMLS, PT.SLM, PT.EBM, PT.BINDER_JET, PT.DED, PT.WAAM})


def default_form(process_types) -> Optional[str]:
    """The form a single price is in when a row lists only processes of one kind."""
    for p in process_types:
        forms = FEEDSTOCK_FORMS.get(p)
        if forms:
            return forms[0]
    return None


def feedstock_price(material: MaterialProfile, process: ProcessType) -> tuple[Optional[float], Optional[str]]:
    """``(USD/kg, form)`` this process pays for ``material``.

    A row that lists no forms keeps its single price. A row that lists forms is
    priced at the first form the process consumes; when it has none of them,
    a printer or deposition cell gets no price (``None``) and every other
    process keeps the row's first-listed price, as before.
    """
    by_form = material.cost_per_kg_by_form or {}
    if not by_form:
        return material.cost_per_kg, material.price_form
    for form in FEEDSTOCK_FORMS.get(process, ()):
        price = by_form.get(form)
        if price is not None:
            return float(price), form
    if process in _FORM_REQUIRED:
        return None, None
    form, price = next(iter(by_form.items()))
    return float(price), form


def priced_for(material: MaterialProfile, process: ProcessType) -> MaterialProfile:
    """A copy of ``material`` whose ``cost_per_kg`` is what ``process`` pays."""
    price, form = feedstock_price(material, process)
    if price == material.cost_per_kg and form == material.price_form:
        return material
    return replace(material, cost_per_kg=price, price_form=form)
