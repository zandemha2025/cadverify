#!/usr/bin/env python3
"""Extract ScaleCAD's full capability surface from the repo.

Sources (nothing skipped that exists in the codebase):
- frontend/src/app/**/page.tsx        -> every routable page
- frontend/src/app/**/route.ts        -> every frontend API route
- backend @router decorators          -> every backend HTTP route (method+path),
  with mount prefixes resolved through main.py's imports and include_router
  calls (the first version of this tool joined prefixes by variable name and
  produced phantom paths like /api/v1/health)
- frontend components                 -> buttons, tabs, dialogs, viewer controls
- exports / downloads                 -> pdf|csv|json|stl|glb triggers
- role/org actions                    -> admin/governance/signoff/members ops
- worker/job states                   -> status enums the product can show

Output: /tmp/scalecad_capabilities.json
"""
from __future__ import annotations
import json, os, re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = "/tmp/scalecad_capabilities.json"


# ---------- frontend pages ----------
def frontend_pages():
    pages = []
    app = os.path.join(ROOT, "frontend/src/app")
    for dirpath, _dirs, files in os.walk(app):
        if "page.tsx" not in files:
            continue
        rel = os.path.relpath(dirpath, app)
        route = "/" if rel == "." else "/" + rel.replace(os.sep, "/")
        route = re.sub(r"\(([^)]+)\)/", "", route)
        route = route.replace("//", "/")
        route = re.sub(r"/\[([^\]]+)\]", r"/{\1}", route)
        src = open(os.path.join(dirpath, "page.tsx"), encoding="utf8", errors="replace").read()
        pages.append({
            "route": route,
            "source": f"frontend/src/app/{os.path.relpath(dirpath, app)}/page.tsx",
            "client_component": '"use client"' in src,
            "lines": src.count("\n"),
        })
    return sorted(pages, key=lambda p: p["route"])


def frontend_api_routes():
    routes = []
    app = os.path.join(ROOT, "frontend/src/app")
    for dirpath, _dirs, files in os.walk(app):
        if "route.ts" not in files:
            continue
        rel = os.path.relpath(dirpath, app)
        route = "/" + rel.replace(os.sep, "/")
        route = re.sub(r"\(([^)]+)\)/", "", route).replace("//", "/")
        src = open(os.path.join(dirpath, "route.ts"), encoding="utf8", errors="replace").read()
        methods = sorted({m.lower() for m in re.findall(r"export\s+async\s+function\s+(GET|POST|PUT|PATCH|DELETE|HEAD)\b", src)})
        routes.append({"route": route, "methods": [m.upper() for m in methods] or ["GET"]})
    return sorted(routes, key=lambda r: r["route"])


# ---------- backend routes: the app's own OpenAPI schema is the ground truth ----------
def backend_routes():
    """Every registered backend HTTP route, method-exact.

    Imported from the FastAPI app when its venv is importable (the app's
    openapi() resolves every lazily-included router — static parsing of
    decorators and mount prefixes guesses wrong, e.g. phantom /api/v1/health).
    Falls back to the static decorator parse for a cold checkout.
    """
    try:
        import json as _json
        import subprocess
        import sys

        code = (
            "from main import app\n"
            "spec = app.openapi()\n"
            "out = {p: sorted(m.upper() for m in ops if m in "
            "('get','post','put','patch','delete','head')) for p, ops in spec['paths'].items()}\n"
            "import json; print(json.dumps(out))\n"
        )
        venv_py = os.path.join(ROOT, "backend/.venv312/bin/python")
        py = venv_py if os.path.exists(venv_py) else sys.executable
        res = subprocess.run([py, "-c", code], cwd=os.path.join(ROOT, "backend"),
                             capture_output=True, text=True, timeout=600)
        line = res.stdout.strip().splitlines()[-1]
        live = _json.loads(line)
        routes = []
        for path, methods in sorted(live.items()):
            for method in methods:
                routes.append({"method": method, "path": path, "file": "backend (app.openapi)"})
        if routes:
            return routes
    except Exception:
        pass
    return _backend_routes_static()
def _read(path):
    return open(path, encoding="utf8", errors="replace").read()


def _balanced(text, start):
    """Text inside the parentheses starting at text[start] == '('."""
    depth, i = 0, start
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
        i += 1
    return text[start + 1 :]


def _backend_routes_static():
    main = _read(os.path.join(ROOT, "backend/main.py"))

    # module -> [(name_in_module, alias_in_main)]
    imports = {}
    for m in re.finditer(r"from\s+(src\.[\w.]+)\s+import\s+([^#\n]+)", main):
        for piece in m.group(2).split(","):
            piece = piece.strip()
            if not piece:
                continue
            im = re.match(r"(\w+)(?:\s+as\s+(\w+))?", piece)
            if im:
                imports.setdefault(m.group(1), []).append((im.group(1), im.group(2) or im.group(1)))

    # alias -> mount prefix (first include wins; aliases are unique per var)
    mounts = {}
    for m in re.finditer(r"\.include_router\(", main):
        inner = _balanced(main, m.end() - 1)
        head = re.match(r"\s*(\w+)\s*,?", inner)
        if not head:
            continue
        pm = re.search(r'prefix="([^"]*)"', inner)
        mounts.setdefault(head.group(1), pm.group(1) if pm else "")

    api_files = []
    for sub in ("src/api", "src/auth"):
        base = os.path.join(ROOT, "backend", sub)
        for dirpath, _d, files in os.walk(base):
            for f in files:
                if f.endswith(".py"):
                    api_files.append(os.path.join(dirpath, f))

    def routes_of_file(path, extra_prefix=""):
        """(router_var, mount_prefix, own_prefix, method, path) per decorator."""
        src = _read(path)
        own = {}
        for m in re.finditer(r"^(\w+)\s*=\s*APIRouter\(([^)]*)", src, re.M | re.S):
            pm = re.search(r'prefix="([^"]*)"', m.group(2))
            own[m.group(1)] = pm.group(1) if pm else ""
        rel = os.path.relpath(path, ROOT)
        out = []
        for m in re.finditer(r"@(\w+)\.(get|post|put|patch|delete)\(\s*(?:path\s*=\s*)?\"([^\"]*)\"", src):
            var, method, pathbit = m.groups()
            out.append((var, own.get(var, ""), method.upper(), pathbit, rel))
        return out

    def module_of(path):
        rel = os.path.relpath(path, ROOT).replace(os.sep, ".")
        return rel[: -len(".py")].replace("backend.", "")

    routes = []
    for path in sorted(set(api_files)):
        mod = module_of(path)
        alias_names = {alias: name for name, alias in imports.get(mod, [])}
        for var, own_prefix, method, pathbit, rel in routes_of_file(path):
            if var in alias_names:
                mount = mounts.get(var, "")
            else:
                mount = ""
            full = mount + own_prefix + pathbit
            routes.append({"method": method, "path": full or "/", "file": rel})

    # SCIM mounts its own sub-application (mount_scim(app)).
    scim = os.path.join(ROOT, "backend/src/api/scim.py")
    if os.path.exists(scim):
        src = _read(scim)
        for m in re.finditer(r"\.include_router\(", src):
            inner = _balanced(src, m.end() - 1)
            head = re.match(r"\s*(\w+)\s*,?", inner)
            pm = re.search(r'prefix="([^"]*)"', inner)
            if head:
                sub = routes_of_file(scim)
                for var, own_prefix, method, pathbit, rel in sub:
                    if var == head.group(1):
                        base = "/api/v1" + (pm.group(1) if pm else "") + own_prefix + pathbit
                        routes.append({"method": method, "path": base, "file": rel})

    seen, out = set(), []
    for r in routes:
        k = (r["method"], r["path"], r["file"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return sorted(out, key=lambda r: (r["path"], r["method"]))


# ---------- interactive surface ----------
def interactive_surface():
    comp_root = os.path.join(ROOT, "frontend/src/components")
    per_file = []
    for dirpath, _d, files in os.walk(comp_root):
        for f in files:
            if not f.endswith((".tsx", ".ts")) or f.endswith(".test.ts"):
                continue
            p = os.path.join(dirpath, f)
            src = open(p, encoding="utf8", errors="replace").read()
            rel = os.path.relpath(p, ROOT)
            buttons = re.findall(r"<Button[^>]*>(?:\s*)?([A-Za-z0-9][^<>{}\n]{1,60})", src)
            aria = re.findall(r'aria-label="([^"]{1,60})"', src)
            tabs = re.findall(r'<TabsTrigger[^>]*>\s*([A-Za-z0-9][^<>{}\n]{1,40})', src)
            dialogs = len(re.findall(r"<Dialog\b|<Sheet\b|<AlertDialog\b", src))
            selects = re.findall(r"<SelectItem[^>]*>\s*([A-Za-z0-9][^<>{}\n]{1,40})", src)
            entry = {
                "file": rel,
                "buttons_sample": buttons[:12],
                "tabs_sample": tabs[:10],
                "selects_sample": selects[:10],
                "aria_labels_sample": aria[:12],
                "dialogs": dialogs,
            }
            if buttons or aria or tabs or selects or dialogs:
                per_file.append(entry)
    return per_file[:200]


def viewer_controls():
    """Files that touch WebGL/three.js or name viewer interactions."""
    hits = []
    base = os.path.join(ROOT, "frontend/src")
    pat = re.compile(r"\b(canvas|WebGL|three|GLTFLoader|OrbitControls|useFrame|mesh\b)", re.I)
    for dirpath, _d, files in os.walk(base):
        for f in files:
            if not f.endswith((".tsx", ".ts")) or f.endswith(".test.ts"):
                continue
            p = os.path.join(dirpath, f)
            src = open(p, encoding="utf8", errors="replace").read()
            tokens = sorted(set(pat.findall(src)))[:8]
            if tokens:
                hits.append({"file": os.path.relpath(p, ROOT), "actions_sample": tokens})
    return hits[:80]


def exports_and_downloads():
    hits = []
    comp_root = os.path.join(ROOT, "frontend/src")
    for dirpath, _d, files in os.walk(comp_root):
        for f in files:
            if not f.endswith((".tsx", ".ts")) or f.endswith(".test.ts"):
                continue
            src = open(os.path.join(dirpath, f), encoding="utf8", errors="replace").read()
            for m in re.finditer(r'(download[A-Za-z]*|export[A-Za-z]*)\w*\(', src):
                rel = os.path.relpath(os.path.join(dirpath, f), ROOT)
                hits.append({"file": rel, "call": m.group(0)})
    backend = [r for r in backend_routes() if re.search(r"(pdf|export|download|csv)", r["path"])]
    return {"frontend_artifacts": hits[:80], "backend_export_routes": backend}


def role_and_org_actions():
    keep = re.compile(r"(admin|governance|approve|signoff|member|invite|role|org|scim|change-request)", re.I)
    out = []
    for r in backend_routes():
        if keep.search(r["path"]) or keep.search(r["file"]):
            out.append(r)
    return out[:200]


def worker_and_job_states():
    """Job-status tokens the jobs/services code can emit."""
    states = set()
    pat = re.compile(r'"(pending|queued|running|done|succeeded|failed|cancelled|timeout)"')
    for sub in ("backend/src/jobs", "backend/src/services"):
        base = os.path.join(ROOT, sub)
        for dirpath, _d, files in os.walk(base):
            for f in files:
                if f.endswith(".py"):
                    src = open(os.path.join(dirpath, f), encoding="utf8", errors="replace").read()
                    states.update(m.group(1) for m in pat.finditer(src))
    return sorted(states)


def main():
    cap = {
        "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "repo_commit": __import__("subprocess").check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "frontend_pages": frontend_pages(),
        "frontend_api_routes": frontend_api_routes(),
        "backend_routes": backend_routes(),
        "interactive_surface": interactive_surface(),
        "viewer_controls": viewer_controls(),
        "exports_and_downloads": exports_and_downloads(),
        "role_and_org_actions": role_and_org_actions(),
        "worker_and_job_states": worker_and_job_states(),
        "counts": {},
    }
    cap["counts"] = {
        "frontend_pages": len(cap["frontend_pages"]),
        "frontend_api_routes": len(cap["frontend_api_routes"]),
        "backend_routes": len(cap["backend_routes"]),
        "component_files_with_interactions": len(cap["interactive_surface"]),
        "viewer_files": len(cap["viewer_controls"]),
        "export_artifacts": len(cap["exports_and_downloads"]["frontend_artifacts"]),
        "role_org_backend_routes": len(cap["role_and_org_actions"]),
        "worker_states": len(cap["worker_and_job_states"]),
    }
    with open(OUT, "w") as f:
        json.dump(cap, f, indent=1)
    print(json.dumps({"wrote": OUT, "counts": cap["counts"]}, indent=2))


if __name__ == "__main__":
    main()
