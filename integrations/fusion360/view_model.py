"""Response → palette view model: what the task pane shows, in plain words.

Pure; unit-tested in CI. Mirrors the backend response contract
(/api/v1/validate + /validate/cost) and never invents a field the response
did not carry.
"""
from __future__ import annotations

from typing import Optional

_SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}


def verdict_line(validation: dict) -> str:
    v = (validation or {}).get("overall_verdict") or "unknown"
    best = (validation or {}).get("best_process") or ""
    words = {"pass": "Manufacturable as drawn", "issues": "Issues to fix",
             "fail": "Not manufacturable as drawn"}.get(v, v)
    return words + (f" — best route: {_process_words(best)}" if best else "")


def _process_words(process: str) -> str:
    return (process or "").replace("_", " ").strip()


def top_issues(validation: dict, limit: int = 8) -> list[dict]:
    """Universal + per-process issues, most severe first, plain-words rows."""
    rows: list[dict] = []
    for issue in (validation or {}).get("universal_issues") or []:
        rows.append(_issue_row(issue, scope="whole part"))
    for score in (validation or {}).get("process_scores") or []:
        for issue in score.get("issues") or []:
            rows.append(_issue_row(issue, scope=_process_words(score.get("process"))))
    rows.sort(key=lambda r: (_SEVERITY_ORDER.get(r["severity"], 9), r["where"]))
    return rows[:limit]


def _issue_row(issue: dict, scope: str) -> dict:
    return {
        "severity": (issue.get("severity") or "INFO").upper(),
        "where": scope,
        "code": issue.get("code") or "",
        "message": issue.get("message") or "",
        "fix": issue.get("fix_suggestion") or "",
    }


def cost_rows(cost: dict) -> list[dict]:
    """One row per process×quantity, cheapest first, with the honesty band."""
    rows = []
    for est in (cost or {}).get("estimates") or []:
        confidence = est.get("confidence") or {}
        rows.append({
            "process": _process_words(est.get("process")),
            "qty": est.get("quantity"),
            "unit_cost_usd": est.get("unit_cost_usd"),
            "band_low": confidence.get("low_usd"),
            "band_high": confidence.get("high_usd"),
            "validated": confidence.get("validated") is True,
            "lead_time": est.get("lead_time"),
        })
    rows.sort(key=lambda r: (r.get("unit_cost_usd") is None,
                             r.get("unit_cost_usd") or 0.0))
    return rows


def recommendation(cost: dict) -> Optional[str]:
    d = (cost or {}).get("decision") or {}
    return d.get("recommendation") or d.get("summary") or None


def deep_link(origin: str, cost: dict) -> str:
    saved = (cost or {}).get("saved") or {}
    if saved.get("id"):
        return origin.rstrip("/") + "/analyses/" + saved["id"]
    return origin.rstrip("/") + "/history"


def geometry_line(validation: dict) -> str:
    g = (validation or {}).get("geometry") or {}
    bbox = g.get("bounding_box_mm") or []
    if len(bbox) == 3:
        return (f"{bbox[0]:.1f} × {bbox[1]:.1f} × {bbox[2]:.1f} mm envelope · "
                f"{g.get('faces', 0):,} faces")
    return ""


def build(origin: str, validation: dict, cost: dict) -> dict:
    """The whole palette payload."""
    return {
        "verdict": verdict_line(validation),
        "geometry": geometry_line(validation),
        "issues": top_issues(validation),
        "costs": cost_rows(cost),
        "recommendation": recommendation(cost),
        "deep_link": deep_link(origin, cost),
    }
