/** One bounded server check groups the preview, DFM and cost of this upload. */
const checks = new WeakMap<File, string>();

export function partCheckHeaders(file: File): Record<string, string> {
  let id = checks.get(file);
  if (!id) {
    id = crypto.randomUUID();
    checks.set(file, id);
  }
  return { "x-part-check-id": id };
}
