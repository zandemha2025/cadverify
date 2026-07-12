import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const app = process.env.FLY_APP_NAME || process.env.CADVERIFY_FLY_APP || "cadvrfy-api";
const requiredGroups = (process.env.FLY_REQUIRED_PROCESS_GROUPS || "web,worker")
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);
const timeoutMs = Number.parseInt(process.env.FLY_PROCESS_READY_TIMEOUT_MS || "120000", 10);
const intervalMs = Number.parseInt(process.env.FLY_PROCESS_READY_INTERVAL_MS || "5000", 10);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fly(args, options = {}) {
  const { stdout, stderr } = await execFileAsync("flyctl", args, {
    maxBuffer: 1024 * 1024 * 8,
    ...options,
  });
  return { stdout, stderr };
}

async function listMachines() {
  const { stdout } = await fly(["machine", "list", "--app", app, "--json"]);
  return JSON.parse(stdout);
}

function processGroup(machine) {
  return (
    machine.config?.env?.FLY_PROCESS_GROUP ||
    machine.config?.metadata?.fly_process_group ||
    machine.process_group ||
    ""
  );
}

function nonTerminalMachines(machines, group) {
  return machines.filter((machine) => {
    if (processGroup(machine) !== group) return false;
    return !["destroyed", "destroying"].includes(machine.state);
  });
}

async function startStoppedRequiredMachines(machines) {
  const starts = [];
  for (const group of requiredGroups) {
    const groupMachines = nonTerminalMachines(machines, group);
    if (groupMachines.length === 0) {
      throw new Error(`No Fly machines found for required process group "${group}" in app ${app}`);
    }
    const started = groupMachines.some((machine) => machine.state === "started");
    if (started) continue;

    const candidate =
      groupMachines.find((machine) => ["stopped", "suspended"].includes(machine.state)) ||
      groupMachines[0];
    console.log(`Starting ${group} machine ${candidate.id} from state ${candidate.state}`);
    await fly(["machine", "start", candidate.id, "--app", app]);
    starts.push({ group, machineId: candidate.id, previousState: candidate.state });
  }
  return starts;
}

function groupSummary(machines) {
  return Object.fromEntries(
    requiredGroups.map((group) => [
      group,
      nonTerminalMachines(machines, group).map((machine) => ({
        id: machine.id,
        state: machine.state,
      })),
    ]),
  );
}

function ready(machines) {
  return requiredGroups.every((group) =>
    nonTerminalMachines(machines, group).some((machine) => machine.state === "started"),
  );
}

async function main() {
  const startedAt = Date.now();
  const attempts = [];
  let starts = [];

  while (Date.now() - startedAt <= timeoutMs) {
    const machines = await listMachines();
    if (starts.length === 0) {
      starts = await startStoppedRequiredMachines(machines);
    }

    const summary = groupSummary(machines);
    attempts.push({
      at: new Date().toISOString(),
      ready: ready(machines),
      summary,
    });
    console.log(JSON.stringify({ app, ready: attempts.at(-1).ready, summary }, null, 2));

    if (attempts.at(-1).ready) {
      console.log(JSON.stringify({ status: "PASS", app, requiredGroups, starts, attempts: attempts.length }, null, 2));
      return;
    }
    await sleep(intervalMs);
  }

  const machines = await listMachines();
  const summary = groupSummary(machines);
  console.error(JSON.stringify({ status: "NEEDS_FIXES", app, requiredGroups, starts, summary }, null, 2));
  process.exitCode = 1;
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : error);
  process.exitCode = 1;
});
