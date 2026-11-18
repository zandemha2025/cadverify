"""ScaleCAD Check — Fusion 360 add-in entry point.

Registers one command ("Check with ScaleCAD") under UTILITIES → ADD-INS.
All Fusion API (`adsk`) imports live in THIS file; the client and view
model are pure modules unit-tested outside Fusion.

Flow: export the active design as STEP AP242 to a temp file → one API-key
check (validate + cost) → render in the ScaleCAD palette with a deep link
to the full report. Settings (API origin + read+write key) live in the
palette's settings tab and on disk at ~/.scalecad-addin/settings.json
(chmod 600). A local friction log (~/.scalecad-addin/friction.jsonl)
records the activation-gate events; nothing leaves the machine.

Manual activation gate (the add-in is DONE only when an engineer who has
never seen it completes a check unaided — see README.md): this file is the
thin layer that can only be exercised inside Fusion.
"""
import json
import os
import tempfile
import traceback

import adsk.core
import adsk.fusion

from scalecad_client import ScaleCadError, check_part
from view_model import build

PALETTE_ID = "ScaleCADPalette"
PALETTE_NAME = "ScaleCAD"
CMD_ID = "ScaleCADCheckCmd"
CMD_NAME = "Check with ScaleCAD"

_SETTINGS_DIR = os.path.expanduser("~/.scalecad-addin")
_SETTINGS_PATH = os.path.join(_SETTINGS_DIR, "settings.json")
_FRICTION_PATH = os.path.join(_SETTINGS_DIR, "friction.jsonl")
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

_app = None
_ui = None
_handlers = []


def _log(event, **fields):
    try:
        os.makedirs(_SETTINGS_DIR, exist_ok=True)
        with open(_FRICTION_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                                 "event": event, **fields}) + "\n")
    except Exception:
        pass


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("origin") and data.get("api_key"):
            return data
    except Exception:
        pass
    return {}


def _save_settings(origin: str, api_key: str, quantities: str) -> None:
    os.makedirs(_SETTINGS_DIR, exist_ok=True)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump({"origin": origin.strip(), "api_key": api_key.strip(),
                   "quantities": quantities.strip() or "50,5000"}, fh)
    os.chmod(_SETTINGS_PATH, 0o600)
    _log("settings_saved")


def _export_step() -> tuple[bytes, str]:
    """The active design as STEP AP242 bytes (silent export, temp file)."""
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None or design.rootComponent is None:
        raise RuntimeError("Open a solid design first (this ran with no active design).")
    import step_export  # the tested export shim, kept separate for clarity
    return step_export.export_active_design_step(design, _THIS_DIR)


def _palette():
    return _ui.palettes.itemById(PALETTE_ID)


def _ensure_palette() -> None:
    if _palette() is not None:
        return
    html = os.path.join(_THIS_DIR, "palette.html")
    _ui.palettes.add(
        PALETTE_ID, PALETTE_NAME, PALETTE_NAME, html, isEditable=False,
        isCloseable=True, isVisible=True, width=380, height=560,
    )


def _palette_post(message: dict) -> None:
    pal = _palette()
    if pal is None:
        return
    _ui.palettes.setItemText(PALETTE_ID, "")
    try:
        pal.sendInfoToHTML("scalecad", json.dumps(message))
    except Exception:
        pass


def _run_check() -> None:
    settings = _load_settings()
    if not settings:
        _ensure_palette()
        _palette_post({"view": "settings", "message":
                       "Paste your API origin and a read+write key from ScaleCAD "
                       "(web app → Settings → Developer), then run Check again."})
        _log("settings_missing")
        return
    try:
        _log("check_started")
        _ensure_palette()
        _palette_post({"view": "busy", "message": "Exporting STEP…"})
        step_bytes, filename = _export_step()
        _palette_post({"view": "busy", "message":
                       f"Analyzing {filename} ({len(step_bytes) / 1e6:.1f} MB)…"})
        result = check_part(
            settings["origin"], settings["api_key"], step_bytes, filename,
            quantities=settings.get("quantities", "50,5000"),
            friction_log=_FRICTION_PATH,
        )
        view = build(settings["origin"], result.get("validation"), result.get("cost"))
        _palette_post({"view": "result", "model": view})
    except ScaleCadError as e:
        _log("check_error", error=str(e), status=e.status)
        _palette_post({"view": "error", "message": str(e), "advice": e.advice})
    except Exception as e:
        _log("check_error", error=repr(e))
        _ui.messageBox("ScaleCAD check failed:\n{}".format(traceback.format_exc()))


class ScaleCadCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        cmd = adsk.core.CommandCreatedEventArgs.cast(args).command
        on_execute = ScaleCadExecuteHandler()
        cmd.execute.add(on_execute)
        _handlers.append(on_execute)


class ScaleCadExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        adsk.core.CommandEventArgs.cast(args)
        _run_check()


class PaletteEventHandler(adsk.core.CustomEventEventHandler):
    """Settings + deep-link events from the palette's HTML."""

    def notify(self, args):
        try:
            arg = json.loads(adsk.core.CustomEventArgs.cast(args).additionalInfo or "{}")
        except Exception:
            return
        if arg.get("event") == "save-settings":
            _save_settings(arg.get("origin", ""), arg.get("api_key", ""),
                           arg.get("quantities", "50,5000"))
            _palette_post({"view": "settings-saved",
                           "message": "Saved. Run “Check with ScaleCAD” on a part."})
        elif arg.get("event") == "open-link":
            adsk.core.Application.get().browserLauncher.launchURL(arg.get("url", ""))


def run(context):
    global _app, _ui
    _app = adsk.core.Application.get()
    _ui = _app.userInterface
    try:
        cmd_defs = _ui.commandDefinitions
        existing = cmd_defs.itemById(CMD_ID)
        if existing:
            existing.deleteMe()
        cmd_def = cmd_defs.addButtonDefinition(
            CMD_ID, CMD_NAME, "Should-cost + DFM check on the active design",
        )
        on_created = ScaleCadCommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)
        addons = _ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
        if addons and not addons.controls.itemById(CMD_ID):
            addons.controls.addCommand(cmd_def)
        _app.registerCustomEvent("ScaleCADPaletteEvent")
        on_palette = PaletteEventHandler()
        _app.customEvent("ScaleCADPaletteEvent").add(on_palette)
        _handlers.append(on_palette)
        _log("addin_loaded")
    except Exception:
        if _ui:
            _ui.messageBox("ScaleCAD add-in failed to load:\n{}".format(traceback.format_exc()))


def stop(context):
    try:
        for handler in _handlers:
            handler = None
        _handlers.clear()
        _ui = None
        _app = None
    except Exception:
        pass
