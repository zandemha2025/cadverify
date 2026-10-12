#!/usr/bin/env python3
"""Assert live local stack isolation and record nonsecret runtime evidence."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from environment import HERE, ROOT, STATE, PROJECT, PORTS, app_env, bootstrap, now, protected_json, status


cfg = bootstrap()
env = app_env(cfg)
assert env["RELEASE"] == "dev" and env["AUTH_MODE"] == "oidc"
assert env["DATABASE_URL"].endswith("@127.0.0.1:18832/scalecad_integration")
assert env["REDIS_URL"] == "redis://127.0.0.1:18879/0"
for key in ("RESEND_API_KEY", "GOOGLE_CLIENT_SECRET", "AWS_ACCESS_KEY_ID", "SENTRY_DSN", "OIDC_ALLOWED_ENDPOINT_ORIGINS"):
    assert key not in env, f"Unexpected externally supplied credential/config: {key}"
for key in ("OBJECT_STORE_LOCAL_ROOT", "CADVERIFY_DATA_DIR", "PDF_CACHE_DIR", "MESH_BLOB_DIR", "DESIGN_BLOB_DIR", "SOURCE_ARTIFACT_BLOB_DIR"):
    assert Path(env[key]).is_relative_to(STATE), f"Storage escaped isolated state: {key}"
assert STATE.stat().st_mode & 0o777 == 0o700
for path in (STATE / "credentials.json", STATE / "browser-login.json", STATE / "compose.env", STATE / "realm/scalecad-integration-realm.json"):
    assert path.stat().st_mode & 0o777 == 0o600, f"Wrong secret file mode: {path.name}"
assert subprocess.check_output(["git", "check-ignore", str(STATE / "browser-login.json")], cwd=ROOT, text=True).strip()
runtime = []
for service in ("postgres", "redis", "keycloak"):
    name = f"{PROJECT}-{service}-1"
    # Captured in memory only. Export a strict nonsecret allowlist, never Config.Env.
    container = json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0]
    assert container["Config"]["Labels"]["com.docker.compose.project"] == PROJECT
    assert container["State"]["Running"] is True
    for bindings in container["NetworkSettings"]["Ports"].values():
        for binding in bindings or []:
            assert binding["HostIp"] == "127.0.0.1", f"Non-loopback binding: {name}"
    mounts = [{key: item.get(key) for key in ("Type", "Name", "Destination", "RW")} for item in container["Mounts"]]
    for mount in mounts:
        if mount["Type"] == "volume":
            assert mount["Name"].startswith(f"{PROJECT}_"), "A shared volume was used"
    image = json.loads(subprocess.check_output(["docker", "image", "inspect", container["Image"]], text=True))[0]
    runtime.append({"service": service, "container_id": container["Id"], "image": container["Config"]["Image"],
                    "image_id": image["Id"], "repo_digests": image.get("RepoDigests", []),
                    "port_bindings": container["NetworkSettings"]["Ports"], "mounts": mounts})
current = status()
assert all(item["running_and_owned"] for item in current["processes"].values())
assert all(item["ok"] for item in current["checks"].values())
health = current["checks"]["api_health"]["response"]
assert health["postgres"] and health["redis"] and health["async"]["worker"] == "ok"
evidence = {"captured_at": now(), "result": "PASS", "source_revision": current["source_revision"],
            "checks": ["no inherited provider credentials", "storage entirely in ignored isolated state",
                       "secret file permissions 600 and directory 700", "all Docker listeners loopback only",
                       "all Docker volumes project scoped", "API/worker/DB/Redis healthy", "actual Keycloak discovery"],
            "runtime": runtime,
            "configuration_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                                      for name in ("compose.yml", "environment.py", "verify_isolation.py")},
            "boundaries": current["boundaries"]}
destination = STATE / "evidence/isolation-verification.json"
protected_json(destination, evidence)
print(f"PASS: live isolated environment verified; evidence: {destination}")
