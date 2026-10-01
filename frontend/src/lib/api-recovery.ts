type ApiProblem = {
  detail?: unknown;
  message?: unknown;
};

function firstProblemText(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (Array.isArray(value)) {
    for (const item of value) {
      const text = firstProblemText(item);
      if (text) return text;
    }
    return null;
  }
  if (value && typeof value === "object") {
    const item = value as { message?: unknown; msg?: unknown; detail?: unknown };
    return (
      firstProblemText(item.message) ??
      firstProblemText(item.msg) ??
      firstProblemText(item.detail)
    );
  }
  return null;
}

export function apiProblemDetail(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return firstProblemText(payload);
  const problem = payload as ApiProblem;
  return firstProblemText(problem.detail) ?? firstProblemText(problem.message);
}

/** Preserve allowance scope: only rolling quotas recover by waiting. */
export function apiQuotaMessage(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const body = payload as { code?: unknown; detail?: unknown; window_days?: unknown };
  const nested = body.detail && typeof body.detail === "object"
    ? body.detail as { code?: unknown; window_days?: unknown } : null;
  const code = nested?.code ?? body.code;
  if (typeof code !== "string" || !["org_validation_cap_exceeded", "user_validation_cap_exceeded", "org_quota_exceeded"].includes(code)) return null;
  const detail = apiProblemDetail(payload);
  const windowDays = nested?.window_days ?? body.window_days;
  // Older servers describe the organization window only in their message.
  const resets = code === "org_quota_exceeded" || (typeof windowDays === "number" && windowDays > 0)
    || /in the trailing [1-9]\d* days/.test(detail ?? "");
  return `Verification allowance used up${resets ? " for now" : ""}. ${detail ? `${detail.replace(/[.!?]+$/, "")}. ` : ""}${resets ? "Retry after the rolling allowance becomes available. " : ""}Contact your workspace administrator or the ProofShape team to review your allowance.`;
}

export function isQuotaErrorMessage(message: string | null | undefined): boolean {
  return /^Verification allowance used up(?: for now)?\./.test(message ?? "");
}

export function isLifetimeQuotaErrorMessage(message: string | null | undefined): boolean {
  return Boolean(message?.startsWith("Verification allowance used up."));
}

/** A failed sign-in service must not be reported as rejected credentials. */
export function authErrorMessage(status: number, payload: unknown, fallback: string): string {
  if (status >= 500 || status === 429) {
    return apiRecoveryMessage({ status, payload, resource: "account" });
  }
  return apiProblemDetail(payload) ?? fallback;
}

export function apiRecoveryMessage({
  status,
  payload,
  resource,
  retryAfter,
}: {
  status: number;
  payload?: unknown;
  resource: string;
  retryAfter?: string | null;
}): string {
  const detail = apiProblemDetail(payload);
  const quota = (status === 403 || status === 429) ? apiQuotaMessage(payload) : null;
  if (quota) return quota;

  if (status === 401) {
    return `Your session expired. Sign in again, then retry the ${resource} action.`;
  }
  if (status === 403) {
    return `You do not have permission to perform this ${resource} action. Ask an organization admin for access.`;
  }
  if (status === 404) {
    return `This ${resource} is no longer available. Return to the list and refresh before trying again.`;
  }
  if (status === 409) {
    return `This ${resource} changed while you were working. Refresh the page, review the saved state, and retry once.`;
  }
  if (status === 422) {
    const validation = detail ?? `The ${resource} input was not accepted.`;
    const separator = /[.!?]$/.test(validation) ? "" : ".";
    return `${validation}${separator} Review the input and try again.`;
  }
  if (status === 429) {
    const wait = retryAfter && /^\d+$/.test(retryAfter)
      ? ` in ${retryAfter} seconds`
      : " shortly";
    return `Too many ${resource} requests were sent. Try again${wait}; your saved data is unchanged.`;
  }
  if (status >= 500) {
    if (detail) {
      return /retry|temporar|unavailable|could not|failed/i.test(detail)
        ? detail
        : `${detail.replace(/[.!?]+$/, "")}. Try again; existing saved data is unchanged.`;
    }
    return `The ${resource} service could not finish this request. Try again; existing saved data is unchanged.`;
  }
  return detail ?? `The ${resource} request failed (${status}). Review the page and try again.`;
}

export function networkRecoveryMessage(resource: string): string {
  return `Connection interrupted during the ${resource} request. Check your network, refresh the saved list, and retry once.`;
}

const API_RESOURCE_ROUTES: Array<[RegExp, string]> = [
  [/\/(?:auth|login|logout|sessions?|password)(?:\/|$)/, "account"],
  [/\/(?:invitations?|invites?)(?:\/|$)/, "invitation"],
  [/\/organizations?(?:\/|$)/, "organization"],
  [/\/(?:api-keys?|developer-keys?)(?:\/|$)/, "API key"],
  [/\/notifications?(?:\/|$)/, "notification"],
  [/\/cost-decisions?(?:\/|$)/, "decision"],
  [/\/(?:batches?|batch-runs?)(?:\/|$)/, "batch"],
  [/\/(?:designs?|design-jobs?)(?:\/|$)/, "design"],
  [/\/(?:rfq|rfq-packages?)(?:\/|$)/, "RFQ package"],
  [/\/integrations?(?:\/|$)/, "integration"],
  [/\/programs?(?:\/|$)/, "program"],
  [/\/machines?(?:\/|$)/, "machine"],
  [/\/(?:rate-cards?|rate-libraries?|calibration)(?:\/|$)/, "rate library"],
  [/\/(?:reconstruct|reconstructions?)(?:\/|$)/, "reconstruction"],
  [/\/jobs?(?:\/|$)/, "job"],
  [/\/analyses?(?:\/|$)/, "analysis"],
  [/\/validate(?:\/|$)/, "verification"],
];

/** Name the user's actual surface in fallback recovery copy. */
export function apiResourceFromUrl(url: string): string {
  let pathname = url;
  try {
    pathname = new URL(url, "http://proofshape.local").pathname;
  } catch {
    // A malformed URL will fail in fetch; retaining the original text still
    // lets the route matchers produce the best available recovery label.
  }
  return API_RESOURCE_ROUTES.find(([pattern]) => pattern.test(pathname))?.[1] ?? "request";
}
