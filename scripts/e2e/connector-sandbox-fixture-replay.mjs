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
const token = process.env.CADVERIFY_API_KEY || process.env.CADVERIFY_SCIM_TOKEN || "";
const secretMarker = "fixture-token";

const artifacts = {
  json: path.join(outputRoot, `connector-sandbox-fixture-replay-${runId}.json`),
  md: path.join(outputRoot, `qa-report-connector-sandbox-fixture-replay-${runId}.md`),
};

const connectorProfiles = {
  "sap_s4hana_product_bom_readonly": {
    label: "SAP S/4HANA sandbox",
    baseUrl: process.env.CADVERIFY_SAP_SANDBOX_URL || "https://sap.example",
  },
  "windchill_part_bom_readonly": {
    label: "PTC Windchill sandbox",
    baseUrl: process.env.CADVERIFY_WINDCHILL_SANDBOX_URL || "https://plm.example",
  },
};

const fixtures = {
  "sap_s4hana_product_bom_readonly": [
    { kind: "product", Product: "VALVE-100", ProductDescription: "Valve body", Material: "316L" },
    { kind: "product", Product: "STEM-200", ProductDescription: "Valve stem", Material: "17-4PH" },
    {
      kind: "bom_item",
      BillOfMaterial: "VALVE-100",
      BillOfMaterialComponent: "STEM-200",
      BillOfMaterialItemQuantity: "2",
      BillOfMaterialItemUnit: "EA",
      BillOfMaterialItemNumber: "0010",
    },
  ],
  "windchill_part_bom_readonly": [
    { kind: "part", ID: "OR:wt.part.WTPart:1", Number: "PUMP-10", Revision: "A", Name: "Pump body", Material: "Duplex 2205" },
    { kind: "part", ID: "OR:wt.part.WTPart:2", Number: "SEAL-20", Revision: "B", Name: "Seal kit", Material: "FKM" },
    { kind: "PartUse", ParentNumber: "PUMP-10", ChildNumber: "SEAL-20", Quantity: 4, Unit: "EA", FindNumber: "0010" },
  ],
};

function assert(condition, detail) {
  if (!condition) throw new Error(detail);
}

function redactText(value) {
  return String(value || "").split(secretMarker).join("[redacted]");
}

function redact(value) {
  return JSON.parse(redactText(JSON.stringify(value ?? null)));
}

async function request(method, urlPath, body = undefined) {
  const response = await fetch(`${apiBase}${urlPath}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = redactText(await response.text());
  let json = null;
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      json = { raw: text.slice(0, 500) };
    }
  }
  return { status: response.status, ok: response.ok, json: redact(json) };
}

async function step(steps, name, fn) {
  const started = Date.now();
  try {
    const evidence = await fn();
    steps.push({ name, status: "PASS", durationMs: Date.now() - started, evidence: redact(evidence) });
    return evidence;
  } catch (error) {
    steps.push({
      name,
      status: "FAIL",
      durationMs: Date.now() - started,
      error: redactText(error instanceof Error ? error.message : String(error)),
    });
    throw error;
  }
}

function normalizeSap(rows) {
  const parts = [];
  const bomNodes = [];
  const warnings = [];
  for (const [index, row] of rows.entries()) {
    const ref = `sap:${index + 1}`;
    const kind = String(row.kind || row.type || "").toLowerCase();
    if (["product", "material", "part"].includes(kind)) {
      const partNumber = String(row.Product || row.Material || row.part_number || "").trim();
      if (!partNumber) {
        warnings.push(`${ref}: missing SAP product/material id`);
        continue;
      }
      parts.push({ part_number: partNumber, revision: row.Revision || null, material: row.Material || null });
    } else if (["bom_item", "bom"].includes(kind)) {
      const parent = String(row.BillOfMaterial || row.parent_part_number || "").trim();
      const child = String(row.BillOfMaterialComponent || row.child_part_number || "").trim();
      if (!parent || !child) {
        warnings.push(`${ref}: missing SAP BOM parent/component`);
        continue;
      }
      bomNodes.push({ parent_part_number: parent, child_part_number: child, quantity: Number(row.BillOfMaterialItemQuantity || row.quantity || 1) });
    } else {
      warnings.push(`${ref}: unsupported SAP record kind '${kind || "unknown"}'`);
    }
  }
  return { parts, bom_nodes: bomNodes, warnings };
}

function normalizeWindchill(rows) {
  const parts = [];
  const bomNodes = [];
  const warnings = [];
  for (const [index, row] of rows.entries()) {
    const ref = `windchill:${index + 1}`;
    const kind = String(row.kind || row["@type"] || row.type || "").toLowerCase();
    if (["part", "wt.part.wtpart"].includes(kind)) {
      const number = String(row.Number || row.number || row.part_number || "").trim();
      if (!number) {
        warnings.push(`${ref}: missing Windchill part number`);
        continue;
      }
      parts.push({ part_number: number, revision: row.Revision || row.version || null, material: row.Material || null });
    } else if (["partuse", "bom_item", "usage"].includes(kind)) {
      const parent = String(row.ParentNumber || row.parent_part_number || "").trim();
      const child = String(row.ChildNumber || row.child_part_number || "").trim();
      if (!parent || !child) {
        warnings.push(`${ref}: missing Windchill BOM parent/child`);
        continue;
      }
      bomNodes.push({ parent_part_number: parent, child_part_number: child, quantity: Number(row.Quantity || row.quantity || 1) });
    } else {
      warnings.push(`${ref}: unsupported Windchill record kind '${kind || "unknown"}'`);
    }
  }
  return { parts, bom_nodes: bomNodes, warnings };
}

function runConnectorFixture(connectorId, rows) {
  const normalized = connectorId.includes("sap")
    ? normalizeSap(rows)
    : normalizeWindchill(rows);
  const passed =
    normalized.parts.length >= 2 &&
    normalized.bom_nodes.length >= 1 &&
    normalized.warnings.length === 0;
  return {
    connectorId,
    status: passed ? "PASS" : "NEEDS_FIXES",
    boundary: "offline sandbox fixture replay, not live vendor certification",
    sourceRecordCount: rows.length,
    normalizedPartCount: normalized.parts.length,
    normalizedBomNodeCount: normalized.bom_nodes.length,
    warnings: normalized.warnings,
    normalized,
  };
}

async function runApiCredentialLifecycle() {
  if (!token) {
    return {
      status: "SKIPPED",
      boundary: "Requires CADVERIFY_API_KEY or CADVERIFY_SCIM_TOKEN for an org-admin user.",
      steps: [],
    };
  }

  const steps = [];
  const failures = [];
  for (const connectorId of Object.keys(fixtures)) {
    const profile = connectorProfiles[connectorId];
    let profileId = null;
    try {
      await step(steps, `${connectorId}: create credential profile`, async () => {
        const created = await request("POST", "/api/v1/integrations/credential-profiles", {
          connector_id: connectorId,
          label: `${profile.label} ${runId} ${Date.now().toString(36)}`,
          base_url: profile.baseUrl,
          auth_type: "bearer",
          secret: { token: `${secretMarker}-${connectorId}-${runId}` },
          metadata: { e2e: "connector-sandbox-fixture-replay", run_id: runId },
        });
        assert(created.status === 201, `create credential profile HTTP ${created.status}: ${JSON.stringify(created.json)}`);
        assert(created.json?.profile?.id, "created profile missing id");
        assert(created.json.profile.connector_id === connectorId, "created profile connector mismatch");
        assert(created.json.profile.secret_fingerprint, "created profile missing fingerprint");
        assert(created.json.profile.secret_fingerprint_algorithm === "hmac_sha256", "fingerprint algorithm mismatch");
        assert(!JSON.stringify(created.json).includes(secretMarker), "create response leaked connector secret");
        profileId = created.json.profile.id;
        return {
          profileId,
          connectorId,
          configured: created.json.profile.configured,
          fingerprintAlgorithm: created.json.profile.secret_fingerprint_algorithm,
        };
      });

      await step(steps, `${connectorId}: probe read-only connector`, async () => {
        const probed = await request("POST", `/api/v1/integrations/credential-profiles/${encodeURIComponent(profileId)}/probe`);
        assert(probed.status === 200, `probe credential profile HTTP ${probed.status}: ${JSON.stringify(probed.json)}`);
        assert(probed.json?.probe?.configured === true, "probe did not mark credential configured");
        assert(probed.json.probe.read_only === true, "probe was not read-only");
        assert(probed.json.probe.boundary_label === "sandbox", "probe boundary was not sandbox");
        assert(!JSON.stringify(probed.json).includes(secretMarker), "probe response leaked connector secret");
        return {
          profileId,
          connectorId,
          configured: probed.json.probe.configured,
          readOnly: probed.json.probe.read_only,
          boundary: probed.json.probe.boundary_label,
        };
      });

      await step(steps, `${connectorId}: revoke credential profile`, async () => {
        const revoked = await request("DELETE", `/api/v1/integrations/credential-profiles/${encodeURIComponent(profileId)}`);
        assert(revoked.status === 200, `revoke credential profile HTTP ${revoked.status}: ${JSON.stringify(revoked.json)}`);
        assert(revoked.json?.profile?.configured === false, "revoked profile still marked configured");
        assert(revoked.json.profile.revoked_at, "revoked profile missing revoked_at");
        assert(!JSON.stringify(revoked.json).includes(secretMarker), "revoke response leaked connector secret");
        return { profileId, connectorId, configured: revoked.json.profile.configured };
      });
    } catch (error) {
      failures.push({
        connectorId,
        error: redactText(error instanceof Error ? error.message : String(error)),
      });
    }
  }

  return {
    status: failures.length === 0 ? "PASS" : "NEEDS_FIXES",
    boundary: "Credential create/probe/revoke lifecycle over the real CadVerify HTTP API; not live SAP/PTC vendor certification.",
    steps,
    failures,
  };
}

function markdown(data) {
  const rows = data.results.map((item) =>
    `| ${item.status} | ${item.connectorId} | ${item.sourceRecordCount} | ${item.normalizedPartCount} | ${item.normalizedBomNodeCount} | ${item.boundary} |`
  ).join("\n");
  const apiRows = (data.apiLifecycle.steps || []).map((item) =>
    `| ${item.status} | ${item.name} | ${item.durationMs} | ${item.error || JSON.stringify(item.evidence).slice(0, 180)} |`
  ).join("\n");
  return `# Connector Sandbox Fixture Replay

- Status: ${data.status}
- Boundary: ${data.boundary}
- API lifecycle: ${data.apiLifecycle.status}

| Result | Connector | Source rows | Parts | BOM nodes | Boundary |
| --- | --- | ---: | ---: | ---: | --- |
${rows}

## API Credential Lifecycle

| Result | Step | Duration ms | Evidence |
| --- | --- | ---: | --- |
${apiRows || `| ${data.apiLifecycle.status} | ${data.apiLifecycle.boundary} | 0 | ${data.apiLifecycle.boundary} |`}
`;
}

async function main() {
  await mkdir(outputRoot, { recursive: true });
  const results = Object.entries(fixtures).map(([connectorId, rows]) => runConnectorFixture(connectorId, rows));
  const apiLifecycle = await runApiCredentialLifecycle();
  const failed = results.filter((item) => item.status !== "PASS");
  const data = {
    status: failed.length === 0 && apiLifecycle.status !== "NEEDS_FIXES" ? "PASS" : "NEEDS_FIXES",
    generatedAt: new Date().toISOString(),
    runId,
    apiBase,
    boundary: "This proves offline sandbox-shaped SAP/Windchill normalization fixtures and, when credentials are present, CadVerify API credential profile lifecycle. It is not live SAP/PTC certification.",
    results,
    apiLifecycle,
    failed,
  };
  await writeFile(artifacts.json, `${JSON.stringify(redact(data), null, 2)}\n`);
  await writeFile(artifacts.md, markdown(redact(data)));
  console.log(JSON.stringify({
    status: data.status,
    connectors: results.length,
    apiLifecycle: apiLifecycle.status,
    report: artifacts.md,
  }, null, 2));
  if (data.status !== "PASS") process.exitCode = 1;
}

main().catch((error) => {
  console.error(redactText(error instanceof Error ? error.stack || error.message : String(error)));
  process.exitCode = 1;
});
