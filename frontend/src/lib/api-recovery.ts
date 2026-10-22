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
  const body = payload as { code?: unknown; detail?: unknown; window_days?: unknown; resets_at?: unknown };
  const nested = body.detail && typeof body.detail === "object"
    ? body.detail as { code?: unknown; window_days?: unknown; resets_at?: unknown } : null;
  const code = nested?.code ?? body.code;
  if (typeof code !== "string" || !["org_validation_cap_exceeded", "user_validation_cap_exceeded", "org_quota_exceeded"].includes(code)) return null;
  const detail = apiProblemDetail(payload);
  const windowDays = nested?.window_days ?? body.window_days;
  const resetsAt = nested?.resets_at ?? body.resets_at;
  const rolling = (typeof windowDays === "number" && windowDays > 0) || /in the trailing [1-9]\d* days/.test(detail ?? "");
  // Older servers describe the organization window only in their message.
  const resets = code === "org_quota_exceeded" || rolling || (typeof resetsAt === "string" && resetsAt.length > 0);
  const sentence = detail ? `${detail.replace(/[.!?]+$/, "")}. ` : "";
  const retry = rolling || code === "org_quota_exceeded" ? "Retry after the rolling allowance becomes available. " : "";
  // A person's own allowance names its plan and next step in the detail itself.
  const contact = code === "user_validation_cap_exceeded" ? "" : "Contact your workspace administrator or the ScaleCAD team to review your allowance.";
  return `Verification allowance used up${resets ? " for now" : ""}. ${sentence}${retry}${contact}`.trim();
}

/** The free allowance needs a verified phone first (SMS_VERIFICATION_REQUIRED). */
export const PHONE_VERIFICATION_PREFIX = "Verify your phone number";

export function isPhoneVerificationMessage(message: string | null | undefined): boolean {
  return Boolean(message?.startsWith(PHONE_VERIFICATION_PREFIX));
}

function phoneVerificationMessage(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const body = payload as { code?: unknown; detail?: { code?: unknown } };
  const code = body.detail && typeof body.detail === "object" ? body.detail.code : body.code;
  if (code !== "phone_verification_required") return null;
  const detail = apiProblemDetail(payload);
  return detail?.startsWith(PHONE_VERIFICATION_PREFIX) ? detail : `${PHONE_VERIFICATION_PREFIX} to start your free checks.`;
}

export function isQuotaErrorMessage(message: string | null | undefined): boolean {
  return /^Verification allowance used up(?: for now)?\./.test(message ?? "");
}

export function isLifetimeQuotaErrorMessage(message: string | null | undefined): boolean {
  return Boolean(message?.startsWith("Verification allowance used up."));
}

/**
 * A refused request's words for a screen that sorts failures by them: an
 * allowance or phone refusal keeps its recognisable lead-in (so it opens Out of
 * checks or the phone check, never "Can't read this file"); anything else is
 * the server's own detail.
 */
export function refusalDetail(status: number, payload: unknown, resource: string): string {
  const recovery = apiRecoveryMessage({ status, payload, resource });
  if (isQuotaErrorMessage(recovery) || isPhoneVerificationMessage(recovery)) return recovery;
  return apiProblemDetail(payload) ?? recovery;
}

/** A failed sign-in service must not be reported as rejected credentials. */
/** A limit's refusal that states its own real wait ("Try again in 37 minutes"):
 *  it carries ``retry_after_seconds``, so its message is shown as it is. */
export function exactWaitMessage(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const body = payload as { retry_after_seconds?: unknown; detail?: unknown };
  const nested = body.detail && typeof body.detail === "object" ? body.detail as { retry_after_seconds?: unknown } : null;
  const wait = nested?.retry_after_seconds ?? body.retry_after_seconds;
  return typeof wait === "number" && wait > 0 ? apiProblemDetail(payload) : null;
}

export function authErrorMessage(status: number, payload: unknown, fallback: string): string {
  if (status === 429) {
    const exact = exactWaitMessage(payload);
    if (exact) return exact;
  }
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
  const body = payload && typeof payload === "object" ? payload as { code?: string; detail?: { code?: string } } : null;
  if (body?.code === "paid_access_required" || body?.detail?.code === "paid_access_required") {
    return detail ?? "This tool is part of a pilot or Enterprise plan. Your plan covers single-part checks.";
  }
  const quota = (status === 403 || status === 429) ? apiQuotaMessage(payload) : null;
  if (quota) return quota;
  const phone = status === 403 ? phoneVerificationMessage(payload) : null;
  if (phone) return phone;

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
