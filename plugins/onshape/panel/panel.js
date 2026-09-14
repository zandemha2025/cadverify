import { ProofShapeClient, createCheckController } from "../../core/src/index.js";
import { OnshapeApiClient, createOnshapeStepExporter, contextFromLocation } from "../src/index.js";

const output = document.querySelector("#output");
const button = document.querySelector("#check");
const config = globalThis.PROOFSHAPE_PLUGIN_CONFIG;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const view = {
  progress(message) {
    button.disabled = true;
    output.innerHTML = `<p>${escapeHtml(message)}</p>`;
  },
  verdict(v) {
    button.disabled = false;
    output.innerHTML = `<span class="badge ${v.badge}">${v.badge}</span>${
      v.issues.length ? `<ul>${v.issues.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : "<p>No issues returned.</p>"
    }${v.sampled ? `<p>Sampled: ${escapeHtml(JSON.stringify(v.sampled))}</p>` : ""}${
      v.provenance ? `<p>Provenance: ${escapeHtml(JSON.stringify(v.provenance))}</p>` : ""
    }${v.recordUrl ? `<p><a target="_blank" rel="noopener" href="${encodeURI(v.recordUrl)}">Open full record</a></p>` : ""}`;
  },
  error(message) {
    button.disabled = false;
    output.innerHTML = `<span class="badge FAIL">FAIL</span><p>${escapeHtml(message)}</p>`;
  },
};

function skeletonNotice(reason) {
  button.disabled = true;
  output.innerHTML = `<p>${escapeHtml(reason)}</p>`;
}

/**
 * Resolve the STEP exporter, in priority order:
 *  1. M1 test harness hook (globalThis.onshapeExportCurrentPartAsStep).
 *  2. Real M2 path: Onshape extension context in the URL plus a relay OAuth
 *     session (?psession=...) -> live OnshapeApiClient + active-part export.
 * Returns null when neither is available (skeleton stays disabled).
 */
async function resolveExporter() {
  if (typeof globalThis.onshapeExportCurrentPartAsStep === "function") {
    return globalThis.onshapeExportCurrentPartAsStep;
  }
  const search = globalThis.location?.search ?? "";
  const sessionId = new URLSearchParams(search).get("psession");
  const context = contextFromLocation(search);
  if (!context || !sessionId) return null;

  const handoff = await fetch(`/session/${encodeURIComponent(sessionId)}/token`, { cache: "no-store" });
  if (!handoff.ok) throw new Error(`Could not collect the Onshape session token (relay returned ${handoff.status}). Restart the sign-in from the relay page.`);
  const token = await handoff.json();

  const client = new OnshapeApiClient({
    apiOrigin: context.apiOrigin,
    accessToken: token.access_token,
    onUnauthorized: async () => {
      const refreshed = await fetch(`/session/${encodeURIComponent(sessionId)}/refresh`, { method: "POST", cache: "no-store" });
      if (!refreshed.ok) return null;
      return (await refreshed.json()).access_token;
    },
  });
  return createOnshapeStepExporter({ client, context });
}

async function boot() {
  if (!config?.apiKey || !config?.baseUrl) {
    skeletonNotice("Skeleton only. Configure a user API key and Onshape STEP export adapter during M2.");
    return;
  }
  let exportStep;
  try {
    exportStep = await resolveExporter();
  } catch (error) {
    skeletonNotice(error instanceof Error ? error.message : String(error));
    return;
  }
  if (!exportStep) {
    skeletonNotice("No Onshape session. Open this panel inside Onshape, or sign in through the local relay so the panel can export the active part.");
    return;
  }
  const controller = createCheckController({
    client: new ProofShapeClient(config),
    view,
    exportStep,
  });
  button.disabled = false;
  button.addEventListener("click", () => controller.check());
}

button.disabled = true;
boot();
