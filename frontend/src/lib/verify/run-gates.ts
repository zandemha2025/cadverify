/** Routing + DFM is the first required gate. A transport/service failure there
 * must not silently fall through to costing and create a contradictory result
 * that looks like the part failed DFM. */
export function validationAllowsCost<T>(validation: T | null): validation is T {
  return validation !== null;
}
