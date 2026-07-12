import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const apiBase = (process.env.CADVERIFY_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const token = process.env.CADVERIFY_SCIM_TOKEN || process.env.CADVERIFY_API_KEY || "";

const artifacts = {
  json: path.join(outputRoot, `scim-idp-lifecycle-${runId}.json`),
  md: path.join(outputRoot, `qa-report-scim-idp-lifecycle-${runId}.md`),
};

function assert(condition, detail) {
  if (!condition) throw new Error(detail);
}

async function request(method, urlPath, body = undefined) {
  const response = await fetch(`${apiBase}${urlPath}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/scim+json, application/json",
      ...(body ? { "Content-Type": "application/scim+json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let json = null;
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      json = { raw: text.slice(0, 500) };
    }
  }
  return { status: response.status, ok: response.ok, json };
}

async function step(steps, name, fn) {
  const started = Date.now();
  try {
    const evidence = await fn();
    steps.push({ name, status: "PASS", durationMs: Date.now() - started, evidence });
    return evidence;
  } catch (error) {
    steps.push({
      name,
      status: "FAIL",
      durationMs: Date.now() - started,
      error: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
}

async function runProvider(provider) {
  const suffix = `${provider.toLowerCase()}-${runId}`.replace(/[^a-z0-9-]/g, "-");
  const email = `scim-${suffix}@example.test`;
  const externalId = `${provider}:${runId}`;
  const steps = [];
  let userId = null;

  await step(steps, `${provider}: service discovery`, async () => {
    const config = await request("GET", "/scim/v2/ServiceProviderConfig");
    assert(config.status === 200, `ServiceProviderConfig HTTP ${config.status}`);
    assert(config.json?.patch?.supported === true, "PATCH not advertised");
    const resourceTypes = await request("GET", "/scim/v2/ResourceTypes");
    assert(resourceTypes.status === 200, `ResourceTypes HTTP ${resourceTypes.status}`);
    const schemas = await request("GET", "/scim/v2/Schemas");
    assert(schemas.status === 200, `Schemas HTTP ${schemas.status}`);
    return {
      patch: config.json.patch,
      resources: resourceTypes.json?.totalResults,
      schemas: schemas.json?.totalResults,
    };
  });

  await step(steps, `${provider}: provision user`, async () => {
    const created = await request("POST", "/scim/v2/Users", {
      schemas: ["urn:ietf:params:scim:schemas:core:2.0:User"],
      externalId,
      userName: email,
      emails: [{ value: email, primary: true }],
      active: true,
      roles: [{ value: "viewer", primary: true }],
    });
    assert(created.status === 201, `create user HTTP ${created.status}`);
    assert(created.json?.active === true, "created user not active");
    assert(created.json?.externalId === externalId, "externalId did not round-trip");
    userId = created.json.id;
    return { id: userId, userName: created.json.userName, active: created.json.active };
  });

  await step(steps, `${provider}: filter user by userName`, async () => {
    const list = await request("GET", `/scim/v2/Users?filter=${encodeURIComponent(`userName eq "${email}"`)}`);
    assert(list.status === 200, `list users HTTP ${list.status}`);
    assert(list.json?.totalResults === 1, `expected one filtered user, got ${list.json?.totalResults}`);
    assert(list.json.Resources?.[0]?.id === userId, "filtered user id mismatch");
    return { totalResults: list.json.totalResults, id: list.json.Resources[0].id };
  });

  await step(steps, `${provider}: group mover to member`, async () => {
    const patched = await request("PATCH", `/scim/v2/Groups/${encodeURIComponent("role:member")}`, {
      schemas: ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
      Operations: [{ op: "add", value: [{ value: userId }] }],
    });
    assert(patched.status === 200, `patch group HTTP ${patched.status}`);
    assert((patched.json?.members || []).some((member) => member.value === userId), "member group missing user");
    const user = await request("GET", `/scim/v2/Users/${encodeURIComponent(userId)}`);
    assert(user.status === 200, `get moved user HTTP ${user.status}`);
    assert(user.json?.roles?.[0]?.value === "member", `role was ${user.json?.roles?.[0]?.value}`);
    return { group: patched.json.id, userRole: user.json.roles[0].value };
  });

  await step(steps, `${provider}: deactivate user`, async () => {
    const patched = await request("PATCH", `/scim/v2/Users/${encodeURIComponent(userId)}`, {
      schemas: ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
      Operations: [{ op: "replace", path: "active", value: false }],
    });
    assert(patched.status === 200, `deactivate HTTP ${patched.status}`);
    assert(patched.json?.active === false, "deactivated user still active");
    const fetched = await request("GET", `/scim/v2/Users/${encodeURIComponent(userId)}`);
    assert(fetched.status === 200, `get inactive user HTTP ${fetched.status}`);
    assert(fetched.json?.active === false, "inactive resource was not preserved");
    return { id: userId, active: fetched.json.active };
  });

  const failed = steps.filter((item) => item.status !== "PASS");
  return {
    provider,
    status: failed.length === 0 ? "PASS" : "NEEDS_FIXES",
    externalId,
    userName: email,
    userId,
    steps,
    failed,
  };
}

function markdown(data) {
  const rows = data.providers.flatMap((provider) =>
    provider.steps.map((item) =>
      `| ${provider.provider} | ${item.status} | ${item.name} | ${item.durationMs} | ${item.error || JSON.stringify(item.evidence).slice(0, 160)} |`
    )
  ).join("\n");
  return `# SCIM IdP Lifecycle

- Status: ${data.status}
- API: ${data.apiBase}
- Boundary: ${data.boundary}

| Provider | Result | Step | Duration ms | Evidence |
| --- | --- | --- | ---: | --- |
${rows}
`;
}

async function main() {
  await mkdir(outputRoot, { recursive: true });
  if (!token) {
    const data = {
      status: "SKIPPED",
      generatedAt: new Date().toISOString(),
      runId,
      apiBase,
      boundary: "Requires CADVERIFY_SCIM_TOKEN or CADVERIFY_API_KEY for an org-admin user.",
      providers: [],
    };
    await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
    await writeFile(artifacts.md, markdown(data));
    console.log(JSON.stringify({ status: data.status, reason: data.boundary, report: artifacts.md }, null, 2));
    return;
  }

  const providers = [];
  for (const provider of ["Okta-sim", "Entra-sim"]) {
    providers.push(await runProvider(provider));
  }
  const failed = providers.filter((provider) => provider.status !== "PASS");
  const data = {
    status: failed.length === 0 ? "PASS" : "NEEDS_FIXES",
    generatedAt: new Date().toISOString(),
    runId,
    apiBase,
    boundary: "SCIM protocol lifecycle simulation over the real CadVerify SCIM HTTP surface; not vendor sandbox certification.",
    providers,
    failed,
  };
  await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(artifacts.md, markdown(data));
  console.log(JSON.stringify({
    status: data.status,
    providers: providers.length,
    failed: failed.map((provider) => provider.provider),
    report: artifacts.md,
  }, null, 2));
  if (data.status !== "PASS") process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
