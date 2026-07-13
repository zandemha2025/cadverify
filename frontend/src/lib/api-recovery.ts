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

function cleanDetail(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return firstProblemText(payload);
  const problem = payload as ApiProblem;
  return firstProblemText(problem.detail) ?? firstProblemText(problem.message);
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
  const detail = cleanDetail(payload);

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
    return `The ${resource} service could not finish this request. Try again; existing saved data is unchanged.`;
  }
  return detail ?? `The ${resource} request failed (${status}). Review the page and try again.`;
}

export function networkRecoveryMessage(resource: string): string {
  return `Connection interrupted during the ${resource} request. Check your network, refresh the saved list, and retry once.`;
}
