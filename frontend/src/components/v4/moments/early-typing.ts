/**
 * Text typed before a page hydrated. On a slow phone the sign-up and sign-in
 * forms show seconds before their scripts run; React keeps what was typed in
 * the DOM through hydration, but the first re-render after it would write the
 * (still empty) state back over it. Call this once, right after hydration, to
 * take what was typed into state instead.
 */
type Field = { value: string };
type Form = { elements: { namedItem(name: string): unknown } };

export function adoptTyped(form: Form | null, fields: Record<string, (value: string) => void>): void {
  if (!form) return;
  for (const [name, set] of Object.entries(fields)) {
    const el = form.elements.namedItem(name) as Field | null;
    if (el && typeof el.value === "string" && el.value) set(el.value);
  }
}
