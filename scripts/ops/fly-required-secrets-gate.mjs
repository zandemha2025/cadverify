import { execFile } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");

const app = process.env.FLY_APP_NAME || process.env.CADVERIFY_FLY_APP || "cadvrfy-api";
const requiredSecrets = (process.env.CADVERIFY_REQUIRED_FLY_SECRETS ||
  "DATABASE_URL,DATABASE_URL_DIRECT,REDIS_URL,SESSION_SECRET,DASHBOARD_SESSION_SECRET,API_KEY_PEPPER,CONNECTOR_SECRET_KEY,CONNECTOR_FINGERPRINT_KEY")
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-");

const artifacts = {
  json: path.join(outputRoot, `fly-required-secrets-gate-${runId}.json`),
  md: path.join(outputRoot, `qa-report-fly-required-secrets-gate-${runId}.md`),
};

async function fly(args) {
  const { stdout } = await execFileAsync("flyctl", args, { maxBuffer: 1024 * 1024 * 4 });
  return stdout;
}

function parseSecretNames(output) {
  return output
    .split(/\r?\n/)
    .map((line) => {
      const parts = line.split("│").map((part) => part.trim()).filter(Boolean);
      return parts.length >= 3 && parts[0] !== "NAME" ? parts[0] : null;
    })
    .filter(Boolean);
}

function markdown(data) {
  const rows = data.requiredSecrets
    .map((name) => `| ${name} | ${data.presentSecrets.includes(name) ? "PASS" : "MISSING"} |`)
    .join("\n");
  return `# Fly Required Secrets Gate

- Status: ${data.status}
- App: ${data.app}
- Required secrets checked: ${data.requiredSecrets.length}
- Missing secrets: ${data.missingSecrets.length ? data.missingSecrets.join(", ") : "none"}

| Secret name | Status |
| --- | --- |
${rows}
`;
}

async function main() {
  await mkdir(outputRoot, { recursive: true });
  const output = await fly(["secrets", "list", "--app", app]);
  const presentSecrets = parseSecretNames(output);
  const missingSecrets = requiredSecrets.filter((name) => !presentSecrets.includes(name));
  const status = missingSecrets.length === 0 ? "PASS" : "NEEDS_FIXES";
  const data = {
    status,
    generatedAt: new Date().toISOString(),
    app,
    requiredSecrets,
    presentSecrets,
    missingSecrets,
  };
  await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(artifacts.md, markdown(data));
  console.log(JSON.stringify({
    status,
    app,
    missingSecrets,
    report: artifacts.md,
  }, null, 2));
  if (status !== "PASS") process.exitCode = 1;
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : error);
  process.exitCode = 1;
});
