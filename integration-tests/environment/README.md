# Isolated local integration environment

This starts the actual ScaleCad API and ARQ worker against a new local PostgreSQL
database and Redis server, plus the official **Keycloak 26.8.0** runtime in its
own container. Keycloak handles a real authorization-code / PKCE S256 exchange;
it is not a custom IdP response fixture. It is **not** evidence that Okta,
Microsoft Entra, Ping, SAP, or Windchill works in a customer tenant.

All ports bind to loopback. Docker Compose uses project `sc-integration-local`
and its own PostgreSQL, Redis and Keycloak volumes. No repository `.env` is read,
no production services are changed and no outbound email is configured. Local
development mode allows HTTP through existing nonproduction code paths; no
production OIDC, webhook or other URL guards are changed.

## Start and inspect

From the repository root:

```sh
python3 integration-tests/environment/environment.py bootstrap
python3 integration-tests/environment/environment.py start
python3 integration-tests/environment/environment.py status
python3 integration-tests/environment/environment.py capture
python3 integration-tests/environment/verify_isolation.py
```

The script uses the existing backend Python venv and frontend Node dependencies.
Their paths are stored in the protected `.state/credentials.json` after bootstrap
and may be edited locally for another workstation. The Next development server
is used; this is not a production image or HTTPS certification environment.

| Surface | Local URL |
|---|---|
| ScaleCad browser login | `http://localhost:18300/login` |
| Begin real OIDC browser flow | `http://localhost:18800/auth/oidc/login` |
| ScaleCad OIDC callback | `http://localhost:18800/auth/oidc/callback` |
| ScaleCad API health | `http://localhost:18800/health` |
| ScaleCad authenticated identity | `http://localhost:18800/auth/me` |
| Same-origin authenticated identity proxy | `http://localhost:18300/api/auth/me/usage` |
| Keycloak discovery | `http://localhost:18080/realms/scalecad-integration/.well-known/openid-configuration` |
| Keycloak account console | `http://localhost:18080/realms/scalecad-integration/account/` |
| PostgreSQL | `127.0.0.1:18832` |
| Redis | `127.0.0.1:18879` |

Read **`.state/browser-login.json`** locally for the synthetic user's username,
password and deliberately wrong password. Do not paste its contents into reports
or logs. `.state/source-claims.json` is the synthetic source-system identity for
reconciliation. Secrets, realm imports, process records, logs and evidence use
mode 600 inside an ignored mode 700 directory.

The realm has registration and password reset disabled, no direct password grant,
no client service accounts and no implicit grant. The confidential ScaleCad client
requires PKCE S256 and has exactly one registered callback. A successful real
browser login should create one identity bound to Keycloak's issuer and subject;
repeat login should resolve that same identity. Use real browser controls for
wrong-password, retry, ScaleCad sign out, and reauthentication. ScaleCad logout
revokes ScaleCad sessions; Keycloak SSO logout is a separate provider operation.

Environment health and discovery evidence do **not** prove successful user login.
Record the actual browser result and reconcile the persisted identity separately.

After real browser tests, read back actual provider events and compare the source
identity with the actual ScaleCad database in a read-only transaction:

```sh
python3 integration-tests/environment/environment.py provider-receipts
/Users/nazeem/Desktop/developer/cadverify/backend/.venv/bin/python integration-tests/environment/database_receipts.py
```

Provider export allows only user identity, group paths, and event metadata.
It omits tokens, passwords, session IDs, authorization codes and event detail
fields. Its admin maintenance token is transient and is not counted as evidence
of customer authentication. ScaleCad reconciliation exports no API keys or
password hashes and reports missing login evidence honestly. No group-to-role
mapping is created just to make a test pass.

## Stop without deleting data

```sh
python3 integration-tests/environment/environment.py stop
```

Only the recorded process groups whose commands still match this environment
are stopped. Compose stops only this project. Database and Keycloak volumes,
credentials and blob files are preserved. There is deliberately no wipe command.
Never use a repository-wide kill script or a global Docker stop for this setup.

Official runtime documentation:

- [Keycloak Docker quick start](https://www.keycloak.org/getting-started/getting-started-docker)
- [Keycloak containers and startup realm import](https://www.keycloak.org/server/containers)
