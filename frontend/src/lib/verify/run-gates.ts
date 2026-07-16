/** Routing + DFM is the first required gate. A transport/service failure there
 * must not silently fall through to costing and create a contradictory result
 * that looks like the part failed DFM. */
export function validationAllowsCost<T>(validation: T | null): validation is T {
  return validation !== null;
}

/** Async UI work may commit only while it still owns the latest sequence token. */
export function isCurrentRun(expected: number, current: number): boolean {
  return expected === current;
}

/** Malformed success bodies are service failures, not reasons to discard an
 * already-rendered routing + DFM result. */
export async function readJsonOrNull<T>(reader: {
  json: () => Promise<unknown>;
}): Promise<T | null> {
  try {
    const value = await reader.json();
    return value == null ? null : value as T;
  } catch {
    return null;
  }
}
