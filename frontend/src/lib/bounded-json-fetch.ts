export class BoundedJsonHttpError extends Error {
  readonly response: Response;

  constructor(response: Response) {
    super(`HTTP ${response.status}`);
    this.name = "BoundedJsonHttpError";
    this.response = response;
  }
}

export async function boundedJsonFetch<T>(
  url: string,
  init: RequestInit = {},
  options: { timeoutMs?: number; getAttempts?: number } = {},
): Promise<T> {
  const method = String(init.method || "GET").toUpperCase();
  const attempts = method === "GET" ? (options.getAttempts ?? 2) : 1;
  const timeoutMs = options.timeoutMs ?? 10_000;
  let lastError: unknown = new Error("request did not run");

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
    const callerSignal = init.signal;
    const abortFromCaller = () => controller.abort();
    callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
    if (callerSignal?.aborted) controller.abort();
    try {
      const response = await fetch(url, { ...init, signal: controller.signal });
      if (!response.ok) throw new BoundedJsonHttpError(response);
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof BoundedJsonHttpError) throw error;
      lastError = error;
      if (callerSignal?.aborted || attempt + 1 >= attempts) throw error;
    } finally {
      globalThis.clearTimeout(timeout);
      callerSignal?.removeEventListener("abort", abortFromCaller);
    }
  }

  throw lastError;
}
