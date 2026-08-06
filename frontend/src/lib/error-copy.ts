/** Keep error cards informative without repeating the same sentence twice. */
export function distinctErrorDetail(
  title: string,
  message?: string,
): string | undefined {
  const detail = message?.trim();
  if (!detail || detail === title.trim()) return undefined;
  return detail;
}
