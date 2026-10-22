"""The pilot report a CEO can read (op-20, op-21): it leads with the run's own answer,
says how many parts it covers and lists the rest, compares wins with what you pay, puts
machine hours against each machine's hours a year, and never splits a decision row."""
from __future__ import annotations

from src.services import pilot_report_service as pr

ANSWER = {"parts": 296, "make": 20, "buy": 6, "decided_buy": 0, "new_machine": 0, "cant_make": 2,
          "not_checked": 268, "not_sorted": 0, "checking": 0, "undecided": 270, "with_price": 256,
          "saving_usd": 398444.7, "saving_parts": 17, "make_without_price": 3, "make_cost_usd": 273909.4}


def test_the_headline_is_the_run_pages_own_words():
    """frontend many/catalog-model.ts answerText: same counts, same money, same words."""
    w = pr.answer_words(ANSWER, True)
    assert w["head"] == ("Make 20 parts in-house: save $398,445 a year against what you pay today "
                         "(on the 17 with a current price)")
    # op-28: a part that can't be made as drawn is answered, not "can't be decided yet".
    assert w["sub"] == ("Buy 6 · 2 can’t be made as drawn · 268 not checked · "
                        "parts on your list, at their listed quantities")
    mixed = pr.answer_words({**ANSWER, "not_checked": 9, "not_sorted": 3, "not_priced": 3, "checking": 4, "undecided": 18}, True)
    assert mixed["sub"] == ("Buy 6 · 2 can’t be made as drawn · 16 can’t be decided yet (9 not checked, 3 not priced yet, "
                            "4 to go) · parts on your list, at their listed quantities")
    assert w["missing"] == "3 in-house parts have no current price, so they aren’t in the saving."
    every = {**ANSWER, "make": 17, "make_without_price": 0, "undecided": 0, "cant_make": 0, "not_checked": 0}
    assert pr.answer_words(every, False)["head"] == "Make these 17 parts in-house: save $398,445 against what you pay today"
    assert pr.answer_words({**ANSWER, "saving_usd": None, "saving_parts": 0}, True)["head"] == "Make 20 parts in-house, buy 6"
    assert pr.answer_words(None, True) is None


def test_coverage_counts_and_lists_every_part_not_checked():
    rows = ([{"bucket": "in_house", "part_number": f"A{i}"} for i in range(20)]
            + [{"bucket": "outside"}] * 6 + [{"bucket": "cant_make"}] * 2
            + [{"bucket": "not_checked", "part_number": f"S{i}", "reason": "Skipped"} for i in range(268)])
    c = pr.coverage(rows)
    assert c["text"] == "28 of 296 checked; 268 not checked"
    # op-28: the run page's breakdown, with the files that aren't on the parts list said apart.
    assert pr.coverage(rows, unlisted=2)["text"] == "28 of 296 checked; 268 not checked; 2 files aren’t on your parts list"
    going = rows[:28] + [{"bucket": "checking", "reason": "Queued"}] * 268 + [{"bucket": "not_sorted", "reason": "x"}] * 3
    g = pr.coverage(going)
    assert g["text"] == "31 of 299 checked; 268 to go; 3 checked without a machine verdict"
    # Parts still to go aren't "not checked": counted apart, and no "not checked" reason is made of them.
    assert (g["not_checked"], g["to_go"], g["left"], g["reasons"]) == (0, 268, 268, [])
    assert len(g["unchecked"]) == 268 and g["unchecked"][0]["reason"] == "Queued"
    assert c["reasons"] == [{"reason": "Skipped", "parts": 268}]
    assert len(c["unchecked"]) == 268 and c["unchecked"][0] == {"part": "S0", "reason": "Skipped"}


def _row(part, *, make, price=None, saving=None, outcome=None, qty=500):
    return {"bucket": "in_house", "part_number": part, "filename": f"{part}.step", "part_key": part, "quantity": qty,
            "route": {"machine": "Haas VF-2"}, "outcome": outcome, "hours_total": 10.0,
            "make": {"process": "cnc_3axis", "machine": "Haas VF-2", "unit_cost_usd": make},
            "current_price": {"usd_each": price, "source": "parts_list"} if price else None,
            "saving": {"each": price - make, "total": (price - make) * qty, "vs": "parts_list"} if price else saving}


def test_biggest_wins_are_against_what_you_pay_where_a_price_is_given():
    rows = [_row("RFS-21061", make=64.81, price=136.07, qty=1000), _row("RFS-21039", make=26.17, price=33.05),
            _row("RFS-21012", make=16.89),  # no price: compared with the model's outside route
            _row("RFS-21040", make=20.0, price=40.0, outcome="supplier")]  # recorded as kept with the supplier
    records = {"RFS-21012": {"result_json": {"decision": {"options": {"500": {
        "in_house": {"process": "cnc_3axis", "unit_cost_usd": 16.89},
        "outside": {"process": "cnc_3axis", "unit_cost_usd": 19.0}}}}}}}
    w = pr.wins(rows, records)
    assert [(x["part_number"], x["vs"], x["outside_each"], x["saving_total"]) for x in w] == [
        ("RFS-21061", "parts_list", 136.07, 71260.0), ("RFS-21039", "parts_list", 33.05, 3440.0),
        ("RFS-21012", "model", 19.0, 1055.0)]
    # A part recorded as bought adds no machine hours either.
    assert pr.machine_hours(rows)[0]["parts"] == 3


def test_the_template_leads_with_the_answer_and_never_splits_a_row():
    html = pr.render_html({
        "organization": "Ridgeline Fluid Systems", "generated_at": "2026-10-22T17:22:00+00:00",
        "scope": {"kind": "run", "created_at": "2026-10-22", "parts_list": {"name": "list.csv"}},
        "answer": ANSWER, "headline": pr.answer_words(ANSWER, True),
        "coverage": pr.coverage([{"bucket": "in_house"}] * 28 + [{"bucket": "not_checked", "reason": "Skipped",
                                                                 "part_number": "RFS-21047"}]),
        "basis": ["Rates: ScaleCAD's typical rates (v0), labor $35/h; publish your own in Rates."],
        "overloaded": ["Lathe: 4,200 h needed of 3,840 h a year (109%)"],
        "parts": 29, "files": 29, "buckets": [], "other": {},
        "in_house": {"parts": 0, "machines": [], "materials": []}, "missing": [], "outside": [], "wins": [],
        "decisions": [{"file_name": "RFS-21040.step", "part_number": "RFS-21040", "decision": "Make in-house",
                       "process": "cnc_3axis", "quantity": 120, "note": "x" * 400, "by": "Dana Ruiz",
                       "at": "2026-10-22", "signoff": {"by": "Dana Ruiz", "at": "2026-10-22", "note": None,
                                                       "stale": False, "stale_reason": None}}],
        "signoffs": {"signed_off": 1, "out_of_date": 0, "recorded": 1},
        "accuracy": {"parts": 1, "enough": False, "min_parts": 8, "hours": {"n": 0}, "cost": {"n": 0},
                     "per_process": []},
        "accuracy_shown": False, "accuracy_rows": [], "calibration": None, "caveats": [],
    })
    lead = html.index("Make 20 parts in-house: save $398,445 a year")
    assert lead < html.index("<h2>Sorted</h2>")
    assert "28 of 29 checked; 1 not checked" in html and "RFS-21047" in html
    assert "Overloaded if every make part comes in-house: Lathe" in html
    assert "tr { page-break-inside: avoid; break-inside: avoid; }" in html
    assert "<td>Dana Ruiz</td>" in html and "at 120" in html
    # One actual is counted, not judged.
    assert "not enough to say how accurate ScaleCAD is for you (8 or more give a fair picture)" in html
    assert "median error" not in html
