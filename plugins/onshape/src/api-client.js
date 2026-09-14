/**
 * Minimal Onshape REST client covering exactly what the M2 adapter needs:
 *
 *   - list parts in the current element:
 *       GET /api/parts/d/{did}/{wv}/{wvid}/e/{eid}
 *   - export the whole part studio to STEP (async):
 *       POST /api/partstudios/d/{did}/{wv}/{wvid}/e/{eid}/export/step
 *   - export selected parts to STEP (async):
 *       POST /api/partstudios/d/{did}/{wv}/{wvid}/e/{eid}/translations
 *       body { formatName: "STEP", partIds: "<id>", storeInDocument: false }
 *   - poll the translation:
 *       GET /api/translations/{tid} until requestState DONE | FAILED
 *   - download the result:
 *       GET /api/documents/d/{did}/externaldata/{fid}
 *       with fid = resultExternalDataIds[0] from the finished translation.
 *
 * Paths and payload fields are taken from the published Onshape OpenAPI
 * documents (partstudio/part/translation/document APIs) and the async export
 * guide at https://onshape-public.github.io/docs/api-adv/translation/.
 *
 * Export responses and downloads can redirect (307). Per the Onshape docs the
 * client must follow the redirect AND re-attach the Authorization header,
 * so redirects are followed manually here.
 */

export class OnshapeApiError extends Error {
  constructor(message, { status, body, translationId } = {}) {
    super(message);
    this.name = "OnshapeApiError";
    this.status = status;
    this.body = body;
    this.translationId = translationId;
  }
}

const TERMINAL_STATES = new Set(["DONE", "FAILED"]);
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);
const MAX_REDIRECTS = 5;

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class OnshapeApiClient {
  constructor({
    apiOrigin = "https://cad.onshape.com",
    accessToken,
    fetchImpl = globalThis.fetch,
    pollIntervalMs = 2_000,
    maxPollMs = 120_000,
    sleep = defaultSleep,
    onUnauthorized,
  }) {
    if (!accessToken) throw new TypeError("accessToken is required (OAuth2 bearer token)");
    if (typeof fetchImpl !== "function") throw new TypeError("fetch implementation is required");
    this.apiOrigin = apiOrigin.replace(/\/$/, "");
    this.accessToken = accessToken;
    this.fetch = fetchImpl;
    this.pollIntervalMs = pollIntervalMs;
    this.maxPollMs = maxPollMs;
    this.sleep = sleep;
    this.onUnauthorized = onUnauthorized;
  }

  headers(extra = {}) {
    return { Authorization: `Bearer ${this.accessToken}`, Accept: "application/json", ...extra };
  }

  async request(path, { method = "GET", body, headers = {}, _retried401 = false, _redirects = 0 } = {}) {
    const url = path.startsWith("http") ? path : `${this.apiOrigin}${path}`;
    const init = { method, headers: this.headers(headers), redirect: "manual" };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
      init.headers["Content-Type"] = "application/json;charset=UTF-8; qs=0.09";
    }
    const response = await this.fetch(url, init);

    if (REDIRECT_STATUSES.has(response.status)) {
      if (_redirects >= MAX_REDIRECTS) {
        throw new OnshapeApiError(`Too many redirects fetching ${path}`, { status: response.status });
      }
      const location = response.headers.get("location");
      if (!location) throw new OnshapeApiError(`Redirect without Location header fetching ${path}`, { status: response.status });
      return this.request(location, { method: "GET", _retried401, _redirects: _redirects + 1 });
    }

    if (response.status === 401 && !_retried401 && typeof this.onUnauthorized === "function") {
      const nextToken = await this.onUnauthorized();
      if (nextToken) {
        this.accessToken = nextToken;
        return this.request(path, { method, body, headers, _retried401: true });
      }
    }

    if (!response.ok) {
      const text = await response.text();
      let parsed = null;
      try { parsed = text ? JSON.parse(text) : null; } catch { parsed = null; }
      throw new OnshapeApiError(
        `Onshape API ${method} ${path} returned ${response.status}: ${parsed?.message ?? text ?? "unknown error"}`,
        { status: response.status, body: parsed ?? text },
      );
    }
    return response;
  }

  async json(path, options) {
    const response = await this.request(path, options);
    const text = await response.text();
    try { return text ? JSON.parse(text) : null; } catch {
      throw new OnshapeApiError(`Onshape API ${path} did not return JSON`, { body: text });
    }
  }

  /** All parts in the current element (BTPartMetadataInfo[]). */
  listParts(context) {
    return this.json(context.partsApiPath());
  }

  /** Async STEP export of the whole part studio. Returns the translation request info. */
  exportStudioStep(context, { destinationName = "proofshape-part" } = {}) {
    return this.json(`${context.elementApiPath()}/export/step`, {
      method: "POST",
      body: {
        storeInDocument: false,
        notifyUser: false,
        destinationName,
        grouping: true,
        excludeHiddenEntities: true,
      },
    });
  }

  /** Async STEP export restricted to specific part ids. Returns the translation request info. */
  exportPartStep(context, partId, { destinationName = "proofshape-part", configuration } = {}) {
    const body = {
      formatName: "STEP",
      partIds: Array.isArray(partId) ? partId.join(",") : String(partId),
      storeInDocument: false,
      notifyUser: false,
      destinationName,
    };
    if (configuration ?? context.configuration) body.configuration = configuration ?? context.configuration;
    return this.json(`${context.elementApiPath()}/translations`, { method: "POST", body });
  }

  /** Poll a translation until requestState is DONE or FAILED. */
  async pollTranslation(translationId, { documentId } = {}) {
    if (!translationId) throw new TypeError("translationId is required");
    const started = Date.now();
    let attempt = 0;
    for (;;) {
      const info = await this.json(`/api/translations/${encodeURIComponent(translationId)}`);
      const state = info?.requestState;
      if (TERMINAL_STATES.has(state)) {
        if (state === "FAILED") {
          throw new OnshapeApiError(
            `Onshape STEP translation failed: ${info?.failureReason ?? "no failure reason returned"}`,
            { translationId, body: info },
          );
        }
        return info;
      }
      if (Date.now() - started >= this.maxPollMs) {
        throw new OnshapeApiError(
          `Onshape STEP translation did not finish within ${Math.round(this.maxPollMs / 1000)}s (still ${state ?? "unknown"})`,
          { translationId, body: info },
        );
      }
      attempt += 1;
      // Respect the documented polling guidance: never faster than the base
      // interval, with a gentle linear backoff on long-running translations.
      await this.sleep(this.pollIntervalMs + Math.min(attempt * 250, 3_000));
    }
  }

  /** Download a finished external-data result as a Blob. */
  async downloadExternalData(documentId, foreignId) {
    if (!documentId || !foreignId) throw new TypeError("documentId and foreignId are required");
    const response = await this.request(
      `/api/documents/d/${encodeURIComponent(documentId)}/externaldata/${encodeURIComponent(foreignId)}`,
    );
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") ?? "";
    const match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(disposition);
    return { blob, filename: match ? decodeURIComponent(match[1].replace(/"$/, "")) : null };
  }

  /**
   * Full active-part STEP export: start the right export, poll to DONE,
   * download the external data. Returns { bytes, filename, translationId, partId }.
   */
  async exportStepForContext(context, { partId, destinationName } = {}) {
    const request = partId
      ? await this.exportPartStep(context, partId, { destinationName })
      : await this.exportStudioStep(context, { destinationName });
    const translationId = request?.id;
    if (!translationId) {
      throw new OnshapeApiError("Onshape did not return a translation id for the STEP export", { body: request });
    }
    const done = await this.pollTranslation(translationId, { documentId: context.documentId });
    const foreignId = done?.resultExternalDataIds?.[0];
    if (!foreignId) {
      throw new OnshapeApiError("Onshape STEP translation finished without result data ids", {
        translationId,
        body: done,
      });
    }
    const { blob, filename } = await this.downloadExternalData(context.documentId, foreignId);
    return {
      bytes: blob,
      filename: filename ?? `${destinationName ?? "proofshape-part"}.step`,
      translationId,
      partId: partId ?? null,
    };
  }
}
