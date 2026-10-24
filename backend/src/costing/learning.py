"""The learning curve: which cost lines learn, and the factor an order of N pays.

Which lines learn. Learning is the time people take falling as they repeat a job;
the time a machine's program sets doesn't fall with repetition. De Jong's model
splits a cycle into a compressible manual part and an incompressible
machine-controlled part, and only the manual part follows the curve (J. R. De Jong,
"The effects of increasing skill on cycle time and its consequences for time
standards", Ergonomics 1(1), 1957, pp. 51-60). So the curve applies to touch labor
(post-process hand work and in-process inspection) and never to machine-paced cycle
time or to the tools and coolant that follow it. Material never learns; setup,
programming and the first article are paid once for the order, so there is nothing
to repeat.

The factor an order pays. The rate card's hours are the standard for the first lot,
so the first ``first_lot`` parts take them in full. Past it each part's time follows
the unit curve, ``(x / first_lot) ** b`` with ``b = log2(rate)`` (Crawford's unit
theory), down to ``floor``. An order of N parts pays the average over its parts, the
sum of the units' times divided by N (the lot average), not the time of its last
part. The sum is taken as the integral of the unit curve:

    A(N) = (first_lot + first_lot * ((N / first_lot) ** (1 + b) - 1) / (1 + b)) / N

e.g. 90% per doubling from a first lot of 100: A(1,000) = 0.813, A(10,000) = 0.584
(the last part's factors are 0.705 and 0.497).
"""

from __future__ import annotations

import math

LEARNING_CITATION = ("De Jong, Ergonomics 1(1) 1957: only the manual share of a cycle "
                     "learns, machine-paced time doesn't")
LEARNS = "touch labor (post-process hand work and in-process inspection)"
DOESNT_LEARN = "machine time (the program sets it), tools and coolant, material, setup and programming"


def unit_factor(rate: float, first_lot: float, floor: float, x: float) -> float:
    """The unit curve's factor for part ``x`` (1 inside the first lot)."""
    if not rate or rate >= 1.0 or first_lot <= 0 or x <= first_lot:
        return 1.0
    b = math.log(rate) / math.log(2.0)
    return max(float(floor or 0.0), (x / first_lot) ** b)


def lot_average_factor(rate: float, first_lot: float, floor: float, qty: float) -> float:
    """The average unit factor over parts 1..``qty`` (1.0 when nothing learns)."""
    q = float(qty)
    f = float(first_lot)
    if not rate or rate >= 1.0 or f <= 0 or q <= f:
        return 1.0
    b = math.log(rate) / math.log(2.0)
    k = 1.0 + b
    floor = float(floor or 0.0)
    # The part where the unit curve reaches its floor (beyond it every part takes the floor).
    x_floor = f * floor ** (1.0 / b) if floor > 0 else math.inf
    upper = min(q, x_floor)
    if abs(k) < 1e-12:
        curve = f * math.log(upper / f)
    else:
        curve = f * ((upper / f) ** k - 1.0) / k
    total = f + curve + (floor * (q - x_floor) if q > x_floor else 0.0)
    return total / q


def learning_words(rate: float, first_lot: float, floor: float, qty: int, factor: float) -> str:
    """The factor's arithmetic, the way a cost engineer rebuilds it."""
    b = math.log(rate) / math.log(2.0)
    k = 1.0 + b
    last = unit_factor(rate, first_lot, floor, qty)
    fl = f"{first_lot:g}"
    return (f"learning curve {rate * 100:g}% per doubling on {LEARNS}, past the first lot of {fl}: "
            f"the order's average part pays ({fl} + {fl} × (({qty:,}/{fl})^{k:.3f} − 1) ÷ {k:.3f}) "
            f"÷ {qty:,} = ×{factor:.3f} (the {qty:,}th part alone ×{last:.3f}; floor {floor:g}). "
            f"Not on {DOESNT_LEARN} ({LEARNING_CITATION}). Rate: typical value, not confirmed by a shop")
