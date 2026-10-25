/**
 * Files handed to a new catalog run from elsewhere (several parts dropped on
 * Home), taken once by the new-run sheet. In memory only: a reload drops them.
 */
let held: File[] | null = null;

export function setPendingBatch(files: File[]): void {
  held = files.length ? [...files] : null;
}

export function takePendingBatch(): File[] | null {
  const f = held;
  held = null;
  return f;
}
