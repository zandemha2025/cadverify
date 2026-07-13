import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const cubePath = path.join(repoRoot, "backend", "tests", "assets", "cube.step");

const artifacts = {
  json: path.join(outputRoot, `enterprise-systems-presence-${runId}.json`),
  md: path.join(outputRoot, `qa-report-enterprise-systems-presence-${runId}.md`),
};

const enterprise = {
  org: {
    name: "MegaEnergy Refining Synthetic Tenant",
    domains: ["megaenergy.example"],
    policy: {
      ssoRequired: true,
      breakGlassAccounts: 2,
      procurementApprovalUsd: 1_000_000,
      noLiveSupplierSend: true,
    },
  },
  users: [
    {
      id: "u-admin",
      userName: "maya.chen@megaenergy.example",
      displayName: "Maya Chen",
      active: true,
      groups: ["cadverify-org-admin", "cadverify-engineering"],
      role: "admin",
    },
    {
      id: "u-engineer",
      userName: "diego.ramos@megaenergy.example",
      displayName: "Diego Ramos",
      active: true,
      groups: ["cadverify-engineering"],
      role: "member",
    },
    {
      id: "u-procurement",
      userName: "arun.patel@megaenergy.example",
      displayName: "Arun Patel",
      active: true,
      groups: ["cadverify-procurement-approver"],
      role: "member",
    },
    {
      id: "u-leaver",
      userName: "lee.jordan@megaenergy.example",
      displayName: "Lee Jordan",
      active: false,
      groups: [],
      role: "viewer",
    },
  ],
  groups: [
    {
      id: "g-admin",
      displayName: "cadverify-org-admin",
      members: ["u-admin"],
      cadverifyRole: "admin",
    },
    {
      id: "g-engineering",
      displayName: "cadverify-engineering",
      members: ["u-admin", "u-engineer"],
      cadverifyRole: "member",
    },
    {
      id: "g-procurement",
      displayName: "cadverify-procurement-approver",
      members: ["u-procurement"],
      cadverifyRole: "procurement_approver",
    },
  ],
  sapProducts: [
    {
      kind: "product",
      Product: "VALVE-100",
      ProductDescription: "Severe-service valve body",
      Material: "316L",
      Plant: "HOU1",
      Program: "REFINERY-TURNAROUND-2026",
      AnnualDemandQty: 12000,
    },
    {
      kind: "product",
      Product: "STEM-200",
      ProductDescription: "Valve stem",
      Material: "17-4PH",
      Plant: "HOU1",
      Program: "REFINERY-TURNAROUND-2026",
      AnnualDemandQty: 24000,
    },
  ],
  sapBom: [
    {
      kind: "bom_item",
      BillOfMaterial: "VALVE-100",
      BillOfMaterialComponent: "STEM-200",
      BillOfMaterialItemQuantity: "2",
      BillOfMaterialItemUnit: "EA",
      BillOfMaterialItemNumber: "0010",
    },
  ],
  windchillParts: [
    {
      kind: "part",
      ID: "OR:wt.part.WTPart:100",
      Number: "VALVE-100",
      Revision: "B",
      Name: "Severe-service valve body",
      Material: "316L",
      LifecycleState: "Released",
      ServiceEnvironment: {
        materialClass: "stainless",
        sourService: true,
        pressureMpa: 35,
        temperatureC: 120,
        standard: "NACE MR0175 / ISO 15156",
      },
    },
    {
      kind: "part",
      ID: "OR:wt.part.WTPart:200",
      Number: "STEM-200",
      Revision: "A",
      Name: "Valve stem",
      Material: "17-4PH",
      LifecycleState: "Released",
      ServiceEnvironment: {
        materialClass: "stainless",
        sourService: true,
        pressureMpa: 35,
        temperatureC: 120,
        standard: "NACE MR0175 / ISO 15156",
      },
    },
  ],
  windchillUses: [
    {
      kind: "PartUse",
      ParentNumber: "VALVE-100",
      ChildNumber: "STEM-200",
      Quantity: 2,
      Unit: "EA",
      FindNumber: "0010",
    },
  ],
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function json(res, status, body) {
  const payload = Buffer.from(`${JSON.stringify(body, null, 2)}\n`);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": String(payload.length),
    "cache-control": "no-store",
  });
  res.end(payload);
}

function text(res, status, body, contentType = "text/plain; charset=utf-8") {
  const payload = Buffer.from(body);
  res.writeHead(status, {
    "content-type": contentType,
    "content-length": String(payload.length),
    "cache-control": "no-store",
  });
  res.end(payload);
}

function notFound(res) {
  json(res, 404, { error: "not_found" });
}

function scimUser(user) {
  return {
    schemas: ["urn:ietf:params:scim:schemas:core:2.0:User"],
    id: user.id,
    userName: user.userName,
    displayName: user.displayName,
    active: user.active,
    emails: [{ value: user.userName, primary: true }],
    groups: user.groups.map((display) => ({ display })),
    "urn:cadverify:params:scim:schemas:enterprise:1.0": {
      role: user.role,
    },
  };
}

function createSimulator(cadBuffer, cadHash) {
  return createServer((req, res) => {
    const host = req.headers.host || "127.0.0.1";
    const url = new URL(req.url || "/", `http://${host}`);

    if (url.pathname === "/health") {
      return json(res, 200, {
        status: "ok",
        org: enterprise.org.name,
        boundary: "synthetic enterprise systems simulator",
      });
    }

    if (url.pathname === "/idp/.well-known/openid-configuration") {
      return json(res, 200, {
        issuer: `http://${host}/idp`,
        authorization_endpoint: `http://${host}/idp/oauth2/v1/authorize`,
        token_endpoint: `http://${host}/idp/oauth2/v1/token`,
        jwks_uri: `http://${host}/idp/oauth2/v1/keys`,
        userinfo_endpoint: `http://${host}/idp/oauth2/v1/userinfo`,
        response_types_supported: ["code"],
        subject_types_supported: ["public"],
        id_token_signing_alg_values_supported: ["RS256"],
        claims_supported: ["sub", "email", "groups", "cadverify_role"],
      });
    }

    if (url.pathname === "/idp/oauth2/v1/keys") {
      return json(res, 200, {
        keys: [
          {
            kty: "RSA",
            kid: "synthetic-key-1",
            use: "sig",
            alg: "RS256",
            n: "synthetic-modulus",
            e: "AQAB",
          },
        ],
        boundary: "metadata only, not a real signing key",
      });
    }

    if (url.pathname === "/saml/metadata") {
      return text(
        res,
        200,
        `<?xml version="1.0" encoding="UTF-8"?>
<EntityDescriptor entityID="http://${host}/saml/idp" xmlns="urn:oasis:names:tc:SAML:2.0:metadata">
  <IDPSSODescriptor WantAuthnRequestsSigned="true" protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="http://${host}/saml/sso"/>
  </IDPSSODescriptor>
</EntityDescriptor>`,
        "application/samlmetadata+xml; charset=utf-8"
      );
    }

    if (url.pathname === "/saml/assertions/admin") {
      const user = enterprise.users[0];
      return json(res, 200, {
        issuer: `http://${host}/saml/idp`,
        audience: "cadverify-enterprise-sp",
        recipient: "http://cadverify.local/auth/saml/acs",
        nameId: user.userName,
        groups: user.groups,
        signed: true,
        replayId: `saml-${runId}-admin`,
        notBefore: new Date(Date.now() - 60_000).toISOString(),
        notOnOrAfter: new Date(Date.now() + 300_000).toISOString(),
        boundary: "synthetic signed-shape assertion, not vendor IdP certification",
      });
    }

    if (url.pathname === "/scim/v2/ServiceProviderConfig") {
      return json(res, 200, {
        schemas: ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        patch: { supported: true },
        bulk: { supported: false, maxOperations: 0, maxPayloadSize: 0 },
        filter: { supported: true, maxResults: 200 },
        changePassword: { supported: false },
        sort: { supported: true },
        etag: { supported: true },
        authenticationSchemes: [{ type: "oauthbearertoken", name: "Bearer token" }],
      });
    }

    if (url.pathname === "/scim/v2/Users") {
      return json(res, 200, {
        schemas: ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        totalResults: enterprise.users.length,
        Resources: enterprise.users.map(scimUser),
      });
    }

    if (url.pathname === "/scim/v2/Groups") {
      return json(res, 200, {
        schemas: ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        totalResults: enterprise.groups.length,
        Resources: enterprise.groups.map((group) => ({
          schemas: ["urn:ietf:params:scim:schemas:core:2.0:Group"],
          id: group.id,
          displayName: group.displayName,
          members: group.members.map((id) => {
            const user = enterprise.users.find((candidate) => candidate.id === id);
            return { value: id, display: user?.userName || id };
          }),
          "urn:cadverify:params:scim:schemas:enterprise:1.0": {
            cadverifyRole: group.cadverifyRole,
          },
        })),
      });
    }

    if (url.pathname === "/sap/opu/odata/sap/API_PRODUCT_SRV/A_Product") {
      return json(res, 200, {
        d: { results: enterprise.sapProducts },
        boundary: "SAP OData-shaped sandbox response, not live SAP certification",
      });
    }

    if (url.pathname === "/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV/A_BillOfMaterialItem") {
      return json(res, 200, {
        d: { results: enterprise.sapBom },
        boundary: "SAP BOM OData-shaped sandbox response, not live SAP certification",
      });
    }

    if (url.pathname === "/Windchill/servlet/odata/ProdMgmt/Parts") {
      return json(res, 200, {
        value: enterprise.windchillParts,
        boundary: "Windchill REST-shaped sandbox response, not live PTC certification",
      });
    }

    if (url.pathname === "/Windchill/servlet/odata/ProdMgmt/PartUses") {
      return json(res, 200, {
        value: enterprise.windchillUses,
        boundary: "Windchill BOM REST-shaped sandbox response, not live PTC certification",
      });
    }

    if (url.pathname === "/procurement/rfq/drafts" && req.method === "POST") {
      let body = "";
      req.on("data", (chunk) => {
        body += chunk.toString("utf8");
      });
      req.on("end", () => {
        let parsed = {};
        try {
          parsed = body ? JSON.parse(body) : {};
        } catch {
          return json(res, 400, { error: "invalid_json" });
        }
        return json(res, 201, {
          id: `rfq-draft-${runId}`,
          status: "draft_created",
          supplierSend: false,
          noLiveSupplierSend: true,
          annualizedValueUsd: Number(parsed.annualizedValueUsd || 0),
          approvalRequired: Number(parsed.annualizedValueUsd || 0) >= enterprise.org.policy.procurementApprovalUsd,
          cxml: {
            messageType: "RequestForQuotation",
            deploymentMode: "test",
            payloadID: `cadverify-${runId}`,
          },
          boundary: "procurement/cXML-shaped draft only, not a live supplier send",
        });
      });
      return;
    }

    if (url.pathname === "/procurement/approvals") {
      return json(res, 200, {
        thresholdUsd: enterprise.org.policy.procurementApprovalUsd,
        chain: [
          { step: "cost_engineering", required: true },
          { step: "procurement", required: true },
          { step: "capital_board", requiredAboveUsd: enterprise.org.policy.procurementApprovalUsd },
        ],
        liveCommitment: false,
      });
    }

    if (url.pathname === "/cad-workstation/session") {
      return json(res, 200, {
        surface: "desktop-cad-workstation",
        host: "synthetic-cad-engineering-vdi",
        installedTools: ["browser STEP viewer", "hash verifier", "CadVerify web app"],
        mountedFiles: [
          {
            name: "cube.step",
            path: "/cad-workstation/files/cube.step",
            sha256: cadHash,
            bytes: cadBuffer.length,
          },
        ],
        boundary: "desktop-shaped CAD workstation simulator, not a native SolidWorks/Inventor plugin",
      });
    }

    if (url.pathname === "/cad-workstation/files/cube.step") {
      res.writeHead(200, {
        "content-type": "model/step",
        "content-length": String(cadBuffer.length),
        "x-cadverify-sha256": cadHash,
        "cache-control": "no-store",
      });
      res.end(cadBuffer);
      return;
    }

    if (url.pathname === "/mobile/ios/manifest.json") {
      return json(res, 200, {
        name: "CadVerify Mobile Field Review",
        short_name: "CadVerify",
        display: "standalone",
        platform: "ios-pwa-surface",
        start_url: "/verify",
        viewport: { width: 390, height: 844, deviceScaleFactor: 3 },
        capabilities: ["review cost decision", "inspect CAD result", "approve RFQ draft"],
        boundary: "mobile web/PWA-shaped surface, not a native iOS App Store build",
      });
    }

    return notFound(res);
  });
}

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert(address && typeof address === "object", "simulator did not expose an address");
  return `http://127.0.0.1:${address.port}`;
}

async function close(server) {
  await new Promise((resolve) => server.close(resolve));
}

async function getJson(baseUrl, pathname, options = {}) {
  const res = await fetch(`${baseUrl}${pathname}`, options);
  const textBody = await res.text();
  let body = {};
  try {
    body = textBody ? JSON.parse(textBody) : {};
  } catch {
    body = { raw: textBody };
  }
  return { status: res.status, headers: Object.fromEntries(res.headers.entries()), body };
}

async function getBytes(baseUrl, pathname) {
  const res = await fetch(`${baseUrl}${pathname}`);
  const buffer = Buffer.from(await res.arrayBuffer());
  return { status: res.status, headers: Object.fromEntries(res.headers.entries()), buffer };
}

async function step(steps, id, surface, fn) {
  const started = Date.now();
  try {
    const evidence = await fn();
    steps.push({ id, surface, status: "PASS", durationMs: Date.now() - started, evidence });
  } catch (error) {
    steps.push({
      id,
      surface,
      status: "FAIL",
      durationMs: Date.now() - started,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

function markdown(data) {
  const rows = data.steps.map((item) => {
    const detail = item.status === "PASS"
      ? JSON.stringify(item.evidence).slice(0, 180)
      : item.error;
    return `| ${item.status} | ${item.id} | ${item.surface} | ${item.durationMs} | ${String(detail).replaceAll("\n", " ")} |`;
  }).join("\n");

  return `# Enterprise Systems Presence

- Date: ${data.runId}
- Status: ${data.status}
- Simulator: ${data.simulatorUrl}
- Boundary: ${data.boundary}

| Result | Check | Surface | Duration ms | Evidence |
| --- | --- | --- | ---: | --- |
${rows}
`;
}

async function main() {
  await mkdir(outputRoot, { recursive: true });
  const cadBuffer = await readFile(cubePath);
  const cadStat = await stat(cubePath);
  const cadHash = createHash("sha256").update(cadBuffer).digest("hex");
  const server = createSimulator(cadBuffer, cadHash);
  const baseUrl = await listen(server);
  const steps = [];

  try {
    await step(steps, "SSO-OIDC-SAML-001", "IdP / SSO", async () => {
      const oidc = await getJson(baseUrl, "/idp/.well-known/openid-configuration");
      assert(oidc.status === 200, `OIDC discovery returned ${oidc.status}`);
      assert(oidc.body.issuer === `${baseUrl}/idp`, "OIDC issuer mismatch");
      assert(oidc.body.claims_supported.includes("groups"), "OIDC groups claim missing");

      const metadata = await fetch(`${baseUrl}/saml/metadata`).then((res) => res.text());
      assert(metadata.includes("EntityDescriptor"), "SAML metadata missing EntityDescriptor");
      assert(metadata.includes("WantAuthnRequestsSigned=\"true\""), "SAML metadata does not require signed requests");

      const assertion = await getJson(baseUrl, "/saml/assertions/admin");
      assert(assertion.status === 200, `SAML assertion returned ${assertion.status}`);
      assert(assertion.body.signed === true, "SAML assertion shape is not signed");
      assert(assertion.body.groups.includes("cadverify-org-admin"), "SAML admin group missing");
      assert(assertion.body.notOnOrAfter, "SAML assertion expiry missing");

      return {
        issuer: oidc.body.issuer,
        groupClaim: true,
        samlSignedShape: assertion.body.signed,
        adminGroups: assertion.body.groups,
      };
    });

    await step(steps, "SCIM-JML-001", "SCIM joiner/mover/leaver", async () => {
      const config = await getJson(baseUrl, "/scim/v2/ServiceProviderConfig");
      const users = await getJson(baseUrl, "/scim/v2/Users");
      const groups = await getJson(baseUrl, "/scim/v2/Groups");
      assert(config.body.patch.supported === true, "SCIM PATCH support missing");
      assert(users.body.totalResults === 4, "SCIM user count mismatch");
      assert(groups.body.totalResults === 3, "SCIM group count mismatch");
      assert(users.body.Resources.some((user) => user.active === false), "SCIM leaver/deactivated user missing");
      assert(groups.body.Resources.some((group) => group.displayName === "cadverify-procurement-approver"), "SCIM procurement group missing");
      return {
        users: users.body.totalResults,
        groups: groups.body.totalResults,
        hasInactiveLeaver: true,
      };
    });

    await step(steps, "SAP-ERP-SANDBOX-001", "SAP S/4HANA OData", async () => {
      const products = await getJson(baseUrl, "/sap/opu/odata/sap/API_PRODUCT_SRV/A_Product");
      const bom = await getJson(baseUrl, "/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV/A_BillOfMaterialItem");
      assert(products.status === 200, `SAP product endpoint returned ${products.status}`);
      assert(bom.status === 200, `SAP BOM endpoint returned ${bom.status}`);
      assert(products.body.d.results.length === 2, "SAP product count mismatch");
      assert(products.body.d.results.some((row) => row.Product === "VALVE-100" && row.Material === "316L"), "SAP VALVE-100 material missing");
      assert(bom.body.d.results[0].BillOfMaterialComponent === "STEM-200", "SAP BOM component mismatch");
      assert(products.body.boundary.includes("not live SAP certification"), "SAP boundary missing");
      return {
        products: products.body.d.results.length,
        bomItems: bom.body.d.results.length,
        annualDemand: products.body.d.results.find((row) => row.Product === "VALVE-100").AnnualDemandQty,
      };
    });

    await step(steps, "PLM-WINDCHILL-SANDBOX-001", "PLM / BOM / service environment", async () => {
      const parts = await getJson(baseUrl, "/Windchill/servlet/odata/ProdMgmt/Parts");
      const uses = await getJson(baseUrl, "/Windchill/servlet/odata/ProdMgmt/PartUses");
      assert(parts.status === 200, `Windchill parts endpoint returned ${parts.status}`);
      assert(uses.status === 200, `Windchill uses endpoint returned ${uses.status}`);
      const valve = parts.body.value.find((row) => row.Number === "VALVE-100");
      assert(valve, "Windchill VALVE-100 missing");
      assert(valve.Revision === "B", "Windchill revision mismatch");
      assert(valve.ServiceEnvironment.sourService === true, "PLM sour-service environment missing");
      assert(valve.ServiceEnvironment.pressureMpa === 35, "PLM pressure environment missing");
      assert(uses.body.value[0].ChildNumber === "STEM-200", "Windchill PartUse child mismatch");
      return {
        parts: parts.body.value.length,
        uses: uses.body.value.length,
        serviceEnvironment: valve.ServiceEnvironment,
      };
    });

    await step(steps, "PROCUREMENT-RFQ-DRAFT-001", "Procurement / RFQ", async () => {
      const draft = await getJson(baseUrl, "/procurement/rfq/drafts", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          partNumber: "VALVE-100",
          annualizedValueUsd: 120_960,
          supplier: "sandbox-supplier",
        }),
      });
      const approvals = await getJson(baseUrl, "/procurement/approvals");
      assert(draft.status === 201, `RFQ draft returned ${draft.status}`);
      assert(draft.body.noLiveSupplierSend === true, "RFQ draft live-send boundary missing");
      assert(draft.body.approvalRequired === false, "RFQ incorrectly required capital-board approval below the $1M policy threshold");
      assert(draft.body.cxml.deploymentMode === "test", "cXML draft is not in test mode");
      assert(draft.body.annualizedValueUsd === 120_960, "RFQ draft annualized value must use the exact-volume $120,960 oracle");
      assert(
        approvals.body.chain.some(
          (item) => item.step === "capital_board" && item.requiredAboveUsd === 1_000_000,
        ),
        "capital-board threshold policy missing",
      );
      return {
        rfqStatus: draft.body.status,
        noLiveSupplierSend: draft.body.noLiveSupplierSend,
        approvalRequired: draft.body.approvalRequired,
      };
    });

    await step(steps, "CAD-WORKSTATION-001", "Desktop CAD workstation-shaped surface", async () => {
      const session = await getJson(baseUrl, "/cad-workstation/session");
      assert(session.status === 200, `CAD workstation session returned ${session.status}`);
      const mounted = session.body.mountedFiles[0];
      assert(mounted.sha256 === cadHash, "workstation file hash does not match local fixture");
      assert(mounted.bytes === cadStat.size, "workstation file byte count does not match local fixture");
      const file = await getBytes(baseUrl, mounted.path);
      assert(file.status === 200, `CAD file fetch returned ${file.status}`);
      const fetchedHash = createHash("sha256").update(file.buffer).digest("hex");
      assert(fetchedHash === cadHash, "fetched CAD file hash mismatch");
      assert(file.headers["x-cadverify-sha256"] === cadHash, "CAD file response hash header missing");
      return {
        filename: mounted.name,
        bytes: mounted.bytes,
        sha256: cadHash,
        boundary: session.body.boundary,
      };
    });

    await step(steps, "MOBILE-IOS-SURFACE-001", "Mobile/iPhone-shaped surface", async () => {
      const manifest = await getJson(baseUrl, "/mobile/ios/manifest.json");
      assert(manifest.status === 200, `mobile manifest returned ${manifest.status}`);
      assert(manifest.body.platform === "ios-pwa-surface", "mobile platform boundary missing");
      assert(manifest.body.viewport.width === 390, "iPhone viewport width mismatch");
      assert(manifest.body.capabilities.includes("approve RFQ draft"), "mobile approval capability missing");
      return {
        platform: manifest.body.platform,
        viewport: manifest.body.viewport,
        capabilities: manifest.body.capabilities,
        boundary: manifest.body.boundary,
      };
    });
  } finally {
    await close(server);
  }

  const failed = steps.filter((item) => item.status !== "PASS");
  const data = {
    status: failed.length === 0 ? "PASS" : "NEEDS_FIXES",
    generatedAt: new Date().toISOString(),
    runId,
    simulatorUrl: baseUrl,
    boundary:
      "This makes enterprise-adjacent systems present as local, deterministic SSO/SCIM/SAP/PLM/procurement/CAD/mobile simulators. It is not vendor certification, native CAD plugin certification, or a live customer tenant.",
    steps,
    failed,
  };

  await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(artifacts.md, markdown(data));
  console.log(JSON.stringify({
    status: data.status,
    surfaces: steps.length,
    failed: failed.map((item) => item.id),
    report: artifacts.md,
  }, null, 2));
  if (data.status !== "PASS") process.exitCode = 1;
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
