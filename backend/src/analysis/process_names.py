"""One plain name per engine process for sentences people read.

The same vocabulary as the v4 screens (frontend/src/components/v4/process-names.ts):
plain words first, with the acronym engineers search for. Engine ids like
``cnc_3axis`` stay in fields; sentences use these names.
"""

from __future__ import annotations

from typing import Iterable

PROCESS_NAME: dict[str, str] = {
    "fdm": "Filament printing",
    "sla": "Resin printing",
    "dlp": "Resin printing",
    "sls": "Nylon powder printing",
    "mjf": "Nylon powder printing",
    "dmls": "Metal powder printing",
    "slm": "Metal powder printing",
    "ebm": "Electron-beam printing",
    "binder_jetting": "Metal binder jetting",
    "ded": "Metal deposition",
    "waam": "Wire-arc printing",
    "cnc_3axis": "3-axis milling",
    "cnc_5axis": "5-axis milling",
    "cnc_turning": "Turning",
    "wire_edm": "Wire EDM",
    "sheet_metal": "Sheet metal",
    "injection_molding": "Injection molding",
    "investment_casting": "Investment casting",
    "die_casting": "Die casting",
    "sand_casting": "Sand casting",
    "forging": "Forging",
}

PROCESS_ACRONYM: dict[str, str] = {
    "fdm": "FDM/FFF",
    "sla": "SLA",
    "dlp": "DLP",
    "sls": "SLS",
    "mjf": "MJF",
    "dmls": "DMLS",
    "slm": "SLM",
    "ebm": "EBM",
    "ded": "DED",
    "waam": "WAAM",
}


def _code(process) -> str:
    return str(getattr(process, "value", process) or "")


def process_label(process) -> str:
    """``"fdm"`` → ``"Filament printing (FDM/FFF)"``; unique per process."""
    code = _code(process)
    if not code:
        return ""
    name = PROCESS_NAME.get(code) or code.replace("_", " ").capitalize()
    acronym = PROCESS_ACRONYM.get(code)
    return f"{name} ({acronym})" if acronym else name


def process_phrase(process) -> str:
    """The label for use mid-sentence: ``"3-axis milling"``, ``"resin printing (SLA)"``."""
    label = process_label(process)
    if not label:
        return ""
    head = label.split(" ", 1)[0]
    # Keep a leading acronym as written ("EDM ..."); lower-case a plain word.
    if head.isupper():
        return label
    return label[:1].lower() + label[1:]


def join_labels(processes: Iterable, *, phrase: bool = False, conjunction: str = "and") -> str:
    """``[fdm, sla]`` → ``"Filament printing (FDM/FFF) and Resin printing (SLA)"``."""
    names = [process_phrase(p) if phrase else process_label(p) for p in processes]
    names = [n for n in names if n]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + f" {conjunction} " + names[-1]
