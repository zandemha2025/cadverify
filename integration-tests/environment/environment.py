#!/usr/bin/env python3
"""An isolated LOCAL ScaleCad stack and actual Keycloak OIDC provider.

Never reads a repository .env. Credentials, realm imports, process records,
logs, blob storage and captured evidence belong to the ignored .state directory.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STATE = HERE / ".state"
PROJECT = "sc-integration-local"
PORTS = {"api": 18800, "frontend": 18300, "keycloak": 18080, "postgres": 18832, "redis": 18879}
ISSUER = "http://localhost:18080/realms/scalecad-integration"
PYTHON_DEFAULT = Path("/Users/nazeem/Desktop/developer/cadverify/backend/.venv/bin/python")
NODE_DEFAULT = Path("/Users/nazeem/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")


def protected_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    path.chmod(0o600)


def revision() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def bootstrap() -> dict:
    STATE.mkdir(mode=0o700, exist_ok=True)
    STATE.chmod(0o700)
    credentials = STATE / "credentials.json"
    if credentials.exists():
        return json.loads(credentials.read_text())
    token = lambda: base64.b64encode(secrets.token_bytes(32)).decode()
    cfg = {
        "postgres_password": secrets.token_hex(24),
        "keycloak_admin_password": secrets.token_urlsafe(30),
        "client_secret": secrets.token_urlsafe(40),
        "test_user_password": secrets.token_urlsafe(26),
        "session_secret": token(),
        "dashboard_session_secret": token(),
        "api_key_pepper": token(),
        "auth_proxy_secret": token(),
        "connector_secret_key": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "test_user_id": str(uuid.uuid4()),
        "python": str(PYTHON_DEFAULT),
        "node": str(NODE_DEFAULT),
    }
    protected_json(credentials, cfg)
    compose_env = STATE / "compose.env"
    compose_env.write_text(
        f"LOCAL_POSTGRES_PASSWORD={cfg['postgres_password']}\n"
        f"LOCAL_KEYCLOAK_ADMIN_PASSWORD={cfg['keycloak_admin_password']}\n"
    )
    compose_env.chmod(0o600)
    realm = {
        "realm": "scalecad-integration", "enabled": True,
        "displayName": "ScaleCad isolated integration QA",
        "registrationAllowed": False, "resetPasswordAllowed": False,
        "loginWithEmailAllowed": True, "duplicateEmailsAllowed": False,
        "sslRequired": "none",
        "eventsEnabled": True, "eventsExpiration": 604800,
        "enabledEventTypes": ["LOGIN", "LOGIN_ERROR", "LOGOUT", "LOGOUT_ERROR", "CODE_TO_TOKEN", "CODE_TO_TOKEN_ERROR"],
        "groups": [{"name": "integration-testers"}],
        "clients": [{
            "clientId": "scalecad-integration", "enabled": True,
            "protocol": "openid-connect", "publicClient": False,
            "secret": cfg["client_secret"], "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False,
            "implicitFlowEnabled": False,
            "redirectUris": ["http://localhost:18800/auth/oidc/callback"],
            "webOrigins": ["http://localhost:18300"],
            "attributes": {"pkce.code.challenge.method": "S256"},
            "protocolMappers": [{
                "name": "integration-groups", "protocol": "openid-connect",
                "protocolMapper": "oidc-group-membership-mapper",
                "consentRequired": False,
                "config": {"claim.name": "groups", "full.path": "true",
                           "id.token.claim": "true", "access.token.claim": "true",
                           "userinfo.token.claim": "true"},
            }],
        }],
        "users": [{
            "id": cfg["test_user_id"], "username": "scalecad-integration-qa",
            "email": "integration.qa@scalecad.invalid", "emailVerified": True,
            "firstName": "Synthetic", "lastName": "Integration QA",
            "enabled": True, "requiredActions": [],
            "groups": ["/integration-testers"],
            "credentials": [{"type": "password", "value": cfg["test_user_password"], "temporary": False}],
        }],
    }
    protected_json(STATE / "realm/scalecad-integration-realm.json", realm)
    protected_json(STATE / "browser-login.json", {
        "login_url": "http://localhost:18800/auth/oidc/login",
        "frontend_login_url": "http://localhost:18300/login",
        "username": "scalecad-integration-qa", "password": cfg["test_user_password"],
        "wrong_password": "deliberately-wrong-local-integration-password",
        "keycloak_account_url": f"{ISSUER}/account/",
    })
    protected_json(STATE / "source-claims.json", {
        "fixture_type": "synthetic user imported into independently running official Keycloak",
        "issuer": ISSUER, "subject": cfg["test_user_id"],
        "email": "integration.qa@scalecad.invalid", "email_verified": True,
        "groups": ["/integration-testers"], "client_id": "scalecad-integration",
        "not_evidence_for": ["Okta", "Microsoft Entra", "Ping", "production HTTPS", "SCIM vendor provisioning"],
    })
    return cfg


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    # Explicit file and env-file prevent Compose from discovering root .env.
    return subprocess.run([
        "docker", "compose", "--project-name", PROJECT,
        "--env-file", str(STATE / "compose.env"), "-f", str(HERE / "compose.yml"), *args,
    ], cwd=HERE, check=check)


def app_env(cfg: dict) -> dict[str, str]:
    # Deliberately allow no inherited service credentials or cloud configuration.
    binary_path = f"{Path(cfg['python']).parent}:{Path(cfg['node']).parent}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    env = {
        "PATH": binary_path, "LANG": "en_US.UTF-8", "TZ": "UTC",
        "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "DYLD_FALLBACK_LIBRARY_PATH": "/opt/homebrew/lib",
        "RELEASE": "dev", "AUTH_MODE": "oidc", "MAGIC_LINK_ENABLED": "0",
        "DATABASE_URL": f"postgresql://scalecad_integration:{cfg['postgres_password']}@127.0.0.1:18832/scalecad_integration",
        "REDIS_URL": "redis://127.0.0.1:18879/0",
        "DASHBOARD_ORIGIN": "http://localhost:18300", "API_ORIGIN": "http://localhost:18800",
        "API_BASE": "http://localhost:18800", "SSO_LOGIN_PATH": "http://localhost:18800/auth/oidc/login",
        "OIDC_ISSUER": ISSUER, "OIDC_CLIENT_ID": "scalecad-integration",
        "OIDC_CLIENT_SECRET": cfg["client_secret"],
        "OIDC_REDIRECT_URI": "http://localhost:18800/auth/oidc/callback",
        "OIDC_SCOPES": "openid email profile", "OIDC_GROUPS_CLAIM": "groups",
        "SESSION_SECRET": cfg["session_secret"],
        "DASHBOARD_SESSION_SECRET": cfg["dashboard_session_secret"],
        "API_KEY_PEPPER": cfg["api_key_pepper"], "AUTH_PROXY_SECRET": cfg["auth_proxy_secret"],
        "CONNECTOR_SECRET_KEY": cfg["connector_secret_key"],
        "ARQ_HEALTH_KEY": "scalecad:integration:worker:health",
        "DESIGN_GENERATION_CONCURRENCY": "1", "PARSE_POOL_WORKERS": "1",
        "RATE_LIBRARY_ENABLED": "1", "OBJECT_STORE_BACKEND": "local",
        "OBJECT_STORE_LOCAL_ROOT": str(STATE / "blobs"),
        "CADVERIFY_DATA_DIR": str(STATE / "corpus-data"),
        "WORKER_STRICT_HEALTH": "1",
        "NEXT_TELEMETRY_DISABLED": "1", "NODE_ENV": "development",
        "PROOFSHAPE_BUILD_ID": revision(), "NEXT_PUBLIC_BUILD_SHA": revision(),
    }
    for name, directory in {
        "MESH_BLOB_DIR": "meshes", "DESIGN_BLOB_DIR": "designs",
        "RECON_BLOB_DIR": "reconstruct", "BATCH_BLOB_DIR": "batch",
        "SOURCE_ARTIFACT_BLOB_DIR": "source-artifacts", "SAM3D_CACHE_DIR": "sam3d-cache",
        "PDF_CACHE_DIR": "pdf-cache",
    }.items():
        path = STATE / "blobs" / directory
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        env[name] = str(path)
    return env


def process_record() -> dict:
    path = STATE / "processes.json"
    return json.loads(path.read_text()) if path.exists() else {}


def process_start_fingerprint(pid: int) -> str:
    return subprocess.check_output(["ps", "-p", str(pid), "-o", "lstart="], text=True).strip()


def owns_process(record: dict) -> bool:
    try:
        pid = int(record["pid"])
        command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True).strip()
        return (os.getpgid(pid) == pid and record["identity"] in command
                and bool(record.get("process_start_fingerprint"))
                and record["process_start_fingerprint"] == process_start_fingerprint(pid))
    except (ProcessLookupError, subprocess.CalledProcessError, KeyError):
        return False


def launch(name: str, command: list[str], cwd: Path, env: dict, identity: str) -> None:
    records = process_record()
    if name in records and owns_process(records[name]):
        return
    log = STATE / f"{name}.log"
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "ab") as stream:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=stream, start_new_session=True)
    records[name] = {"pid": process.pid, "identity": identity, "started_at": now(), "source_revision": revision(),
                     "process_start_fingerprint": process_start_fingerprint(process.pid)}
    protected_json(STATE / "processes.json", records)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def served_revision() -> str:
    """Report the actual HTTP process build; never substitute checkout HEAD."""
    try:
        return str(fetch_json("http://127.0.0.1:18800/health").get("build_id") or "unknown")
    except (OSError, urllib.error.HTTPError):
        return "unverified_api_unavailable"


def wait_url(url: str, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if 200 <= response.status < 400:
                    return
        except (OSError, urllib.error.HTTPError):
            pass
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for local URL {url}; inspect protected .state logs")


def start() -> None:
    cfg = bootstrap()
    for component, port in PORTS.items():
        if component in {"api", "frontend"} and owns_process(process_record().get(component, {})):
            continue
        # Docker services are reused by the isolated compose project only.
        if component not in {"api", "frontend"}:
            continue
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} is occupied; refusing to touch its existing process")
    compose("up", "-d", "--wait", "postgres", "redis", "keycloak")
    wait_url(f"{ISSUER}/.well-known/openid-configuration")
    env = app_env(cfg)
    migration_log = STATE / "migrate.log"
    fd = os.open(migration_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "ab") as stream:
        subprocess.run([cfg["python"], "-m", "alembic", "upgrade", "head"],
                       cwd=ROOT / "backend", env=env, stdout=stream, stderr=stream, check=True)
    launch("api", [cfg["python"], "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                   "--port", "18800", "--no-access-log", "--no-server-header"],
           ROOT / "backend", env, "uvicorn main:app --host 127.0.0.1 --port 18800")
    launch("worker", [cfg["python"], "-m", "arq", "src.jobs.worker.WorkerSettings"],
           ROOT / "backend", env, "arq src.jobs.worker.WorkerSettings")
    # Next reads environment files from its project directory. Refuse to launch
    # if any real file is present; .env.example is documentation only.
    loaded_env_names = (".env", ".env.local", ".env.development", ".env.development.local")
    if any((ROOT / "frontend" / name).exists() for name in loaded_env_names):
        raise RuntimeError("Frontend has an environment file; refusing possible production configuration inheritance")
    launch("frontend", [cfg["node"], str(ROOT / "frontend/node_modules/next/dist/bin/next"),
                        "dev", "--hostname", "127.0.0.1", "--port", "18300"],
           ROOT / "frontend", env, "next/dist/bin/next dev --hostname 127.0.0.1 --port 18300")
    wait_url("http://127.0.0.1:18800/health")
    wait_url("http://localhost:18300/login")
    capture()
    print("Local integration environment ready. Login: http://localhost:18300/login")
    print(f"Protected browser login material: {STATE / 'browser-login.json'}")


def status() -> dict:
    report = {"captured_at": now(), "source_revision": served_revision(), "repository_revision": revision(),
              "environment": "isolated local nonproduction",
              "compose_project": PROJECT, "ports": PORTS, "processes": {}, "checks": {},
              "real_external_runtime": "official Keycloak 26.8.0, independently running container",
              "production_configuration_loaded": False,
              "boundaries": ["local HTTP only", "Next development server", "not vendor-specific certification",
                             "no SAP/Windchill/Okta/Entra/Ping tenant connected", "no outbound email provider configured"]}
    for name, record in process_record().items():
        report["processes"][name] = {**record, "running_and_owned": owns_process(record)}
    for name, url in {
        "api_health": "http://127.0.0.1:18800/health",
        "oidc_status": "http://127.0.0.1:18800/auth/oidc/status",
        "keycloak_discovery": f"{ISSUER}/.well-known/openid-configuration",
    }.items():
        try:
            value = fetch_json(url)
            if name == "keycloak_discovery":
                value = {key: value.get(key) for key in ["issuer", "authorization_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint", "code_challenge_methods_supported"]}
            report["checks"][name] = {"ok": True, "url": url, "response": value}
        except Exception as exc:
            report["checks"][name] = {"ok": False, "url": url, "error_type": type(exc).__name__}
    return report


def capture() -> None:
    protected_json(STATE / "evidence/environment-status.json", status())
    # Image IDs/digests and port bindings are safe; do not dump container env.
    output = subprocess.check_output([
        "docker", "compose", "--project-name", PROJECT, "--env-file", str(STATE / "compose.env"),
        "-f", str(HERE / "compose.yml"), "ps", "--format", "json",
    ], cwd=HERE, text=True)
    protected_json(STATE / "evidence/compose-status.json", [json.loads(line) for line in output.splitlines() if line.strip()])


def provider_receipts() -> None:
    """Read real provider state; admin maintenance auth is not application SSO proof.

    The transient admin token/password, user credentials, sessions and event
    detail fields (which can contain codes) never enter an evidence artifact.
    """
    cfg = bootstrap()
    request = urllib.request.Request(
        "http://127.0.0.1:18080/realms/master/protocol/openid-connect/token",
        data=urllib.parse.urlencode({"grant_type": "password", "client_id": "admin-cli",
                                     "username": "local-integration-admin",
                                     "password": cfg["keycloak_admin_password"]}).encode(),
        headers={"content-type": "application/x-www-form-urlencoded"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        token = json.load(response)["access_token"]

    def admin_get(path: str) -> object:
        req = urllib.request.Request(
            f"http://127.0.0.1:18080/admin/realms/scalecad-integration/{path}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)

    user = admin_get(f"users/{cfg['test_user_id']}")
    groups = admin_get(f"users/{cfg['test_user_id']}/groups")
    events = admin_get("events?max=100")
    realm = admin_get("")
    clients = admin_get("clients?clientId=scalecad-integration&search=false")
    clients = [client for client in clients if client.get("clientId") == "scalecad-integration"]
    if len(clients) != 1:
        raise RuntimeError("Expected exactly one actual ScaleCad Keycloak client; refusing ambiguous configuration proof")
    client = clients[0]
    evidence = {
        "captured_at": now(), "source_revision": served_revision(), "repository_revision": revision(), "issuer": ISSUER,
        "provider": "official Keycloak 26.8.0 self-hosted local test runtime",
        "user": {key: user.get(key) for key in ("id", "username", "email", "emailVerified", "enabled", "firstName", "lastName")},
        "groups": [{key: group.get(key) for key in ("id", "name", "path")} for group in groups],
        "events": [{key: event.get(key) for key in ("id", "time", "type", "realmId", "clientId", "userId", "ipAddress", "error")} for event in events],
        "realm_configuration": {key: realm.get(key) for key in (
            "id", "realm", "enabled", "sslRequired", "eventsEnabled", "eventsExpiration", "enabledEventTypes",
            "registrationAllowed", "resetPasswordAllowed", "loginWithEmailAllowed", "duplicateEmailsAllowed",
        )},
        "client_configuration": {**{key: client.get(key) for key in (
            "id", "clientId", "enabled", "protocol", "publicClient", "standardFlowEnabled",
            "directAccessGrantsEnabled", "serviceAccountsEnabled", "implicitFlowEnabled", "redirectUris", "webOrigins",
        )}, "pkce_attributes": {key: client.get("attributes", {}).get(key) for key in ("pkce.code.challenge.method",)}},
        "application_authentication_evidence": "Only actual LOGIN/CODE_TO_TOKEN events for scalecad-integration count; this admin read-back is not user authentication",
    }
    protected_json(STATE / "evidence/keycloak-provider-receipts.json", evidence)
    print(f"Sanitized actual Keycloak read-back saved to {STATE / 'evidence/keycloak-provider-receipts.json'}")


def stop() -> None:
    for name, record in process_record().items():
        if owns_process(record):
            os.killpg(int(record["pid"]), signal.SIGTERM)
            print(f"Stopped own {name} process group")
    # Deliberately preserves all database/blob/Keycloak volumes and state.
    if (STATE / "compose.env").exists():
        compose("stop")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["bootstrap", "start", "status", "capture", "provider-receipts", "stop"])
    args = parser.parse_args()
    if args.action == "bootstrap":
        bootstrap()
        print(f"Fresh local-only credentials are stored in {STATE}; secret values are not printed")
    elif args.action == "start":
        start()
    elif args.action == "stop":
        stop()
    elif args.action == "capture":
        capture()
        print(f"Sanitized environment evidence saved under {STATE / 'evidence'}")
    elif args.action == "provider-receipts":
        provider_receipts()
    else:
        print(json.dumps(status(), indent=2))
