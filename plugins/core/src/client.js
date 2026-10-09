const TERMINAL = new Set(["done", "partial", "failed"]);

export class ProofShapeApiError extends Error {
  constructor(message, { status, code, body } = {}) {
    super(message);
    this.name = "ProofShapeApiError";
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

function joinUrl(base, path) {
  return new URL(path, `${base.replace(/\/$/, "")}/`).toString();
}

async function parseResponse(response) {
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) {
    const detail = body?.detail;
    const message = detail?.message ?? detail ?? body?.message ?? `ProofShape API returned ${response.status}`;
    throw new ProofShapeApiError(String(message), {
      status: response.status,
      code: detail?.code ?? body?.code,
      body,
    });
  }
  return body;
}

/**
 * Issue rows from the real /validate contract and its predecessors:
 *   - priority_fixes (current API: flat, severity-ordered, deduped)
 *   - top-level issues / violations / findings (earlier shapes and tests)
 *   - process_scores[].issues (per-process nesting in the current API)
 */
function collectIssueRows(result) {
  if (Array.isArray(result?.priority_fixes)) return result.priority_fixes;
  const topLevel = result?.issues ?? result?.violations ?? result?.findings;
  if (Array.isArray(topLevel)) return topLevel;
  if (Array.isArray(result?.process_scores)) {
    return result.process_scores.flatMap((score) => (Array.isArray(score?.issues) ? score.issues : []));
  }
  return [];
}

function formatIssue(row) {
  if (typeof row === "string") return row;
  if (row == null || typeof row !== "object") return String(row);
  const message = row.message ?? row.title ?? JSON.stringify(row);
  const fix = row.fix ?? row.fix_suggestion;
  return fix ? `${message} (Fix: ${fix})` : message;
}

export class ProofShapeClient {
  constructor({ baseUrl, apiKey, fetchImpl = globalThis.fetch, pollIntervalMs = 1000, maxPolls = 120 }) {
    if (!baseUrl) throw new TypeError("baseUrl is required");
    if (!apiKey) throw new TypeError("apiKey is required; user supplies it at install time");
    if (typeof fetchImpl !== "function") throw new TypeError("fetch implementation is required");
    this.baseUrl = baseUrl;
    this.apiKey = apiKey;
    this.fetch = fetchImpl;
    this.pollIntervalMs = pollIntervalMs;
    this.maxPolls = maxPolls;
  }

  headers(extra = {}) {
    return { Authorization: `Bearer ${this.apiKey}`, Accept: "application/json", ...extra };
  }

  async validateStep({ bytes, filename = "part.step", source, signal }) {
    if (!source?.host || !source?.workspaceId || !source?.documentId || !source?.revisionId) {
      throw new TypeError("source host, workspace, document, and revision identity are required");
    }
    if (source.host === "onshape") {
      if (!source.elementId || !source.partId || !source.microversionId) {
        throw new TypeError("Onshape export requires element, part, and immutable microversion identity");
      }
      if (source.revisionId !== source.microversionId) {
        throw new TypeError("Onshape revision must equal the exported immutable microversion");
      }
    }
    if (!/\.(?:step|stp)$/i.test(filename)) {
      throw new TypeError("host connector must export STEP/STP, never a native CAD document");
    }
    if (!(bytes instanceof Blob)) bytes = new Blob([bytes], { type: "application/step" });
    const form = new FormData();
    form.append("file", bytes, filename);
    form.append("connector_source", JSON.stringify(source));
    const response = await this.fetch(joinUrl(this.baseUrl, "/api/v1/validate"), {
      method: "POST", headers: this.headers(), body: form, signal,
    });
    const submitted = await parseResponse(response);
    if (response.status !== 202 && !submitted?.job_id && !submitted?.poll_url) return this.normalizeVerdict(submitted);
    return this.pollValidation(submitted, { signal });
  }

  async pollValidation(submitted, { signal } = {}) {
    const pollUrl = submitted.poll_url ?? `/api/v1/jobs/${encodeURIComponent(submitted.job_id)}`;
    for (let attempt = 0; attempt < this.maxPolls; attempt += 1) {
      if (attempt > 0) await new Promise((resolve, reject) => {
        const timer = setTimeout(resolve, this.pollIntervalMs);
        signal?.addEventListener("abort", () => { clearTimeout(timer); reject(signal.reason); }, { once: true });
      });
      const status = await parseResponse(await this.fetch(joinUrl(this.baseUrl, pollUrl), {
        headers: this.headers(), signal,
      }));
      if (!TERMINAL.has(status.status)) continue;
      if (status.status === "failed") throw new ProofShapeApiError(status.error?.message ?? "Validation failed", { code: status.error?.code, body: status });
      const resultUrl = status.result_url ?? `/api/v1/jobs/${encodeURIComponent(status.job_id)}/result`;
      const resultEnvelope = await parseResponse(await this.fetch(joinUrl(this.baseUrl, resultUrl), {
        headers: this.headers(), signal,
      }));
      return this.normalizeVerdict(resultEnvelope.result ?? resultEnvelope);
    }
    throw new ProofShapeApiError("Validation did not finish before the polling limit", { code: "poll_timeout" });
  }

  normalizeVerdict(result) {
    const raw = String(result?.overall_verdict ?? result?.verdict ?? "issues").toLowerCase();
    const badge = raw === "pass" ? "PASS" : raw === "fail" ? "FAIL" : "ISSUES";
    const issueRows = collectIssueRows(result);
    const issues = issueRows.map((row) => formatIssue(row));
    const recordPath = result?.share_url ?? result?.record_url ?? null;
    return {
      badge,
      issues,
      recordUrl: recordPath ? joinUrl(this.baseUrl, recordPath) : null,
      sampled: result?.sampled ?? result?.sampling ?? null,
      provenance: result?.provenance ?? null,
      raw: result,
    };
  }
}
