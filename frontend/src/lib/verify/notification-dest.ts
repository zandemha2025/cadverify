export type NotificationDestination = "records" | "calibration" | "verify";

const DESTINATIONS = new Set<NotificationDestination>([
  "records",
  "calibration",
  "verify",
]);

export function notificationHref(
  dest: NotificationDestination,
  source?: { source_type?: string; source_id?: string },
): string {
  if (source?.source_type === "cost_decision" && /^[0-7][0-9A-HJKMNP-TV-Z]{25}$/.test(source.source_id ?? "")) {
    return `/cost-decisions/${source.source_id}`;
  }
  return `/verify?screen=${encodeURIComponent(dest)}`;
}

export function notificationScreenFromSearch(
  search: string,
): NotificationDestination | null {
  const value = new URLSearchParams(search).get("screen");
  return DESTINATIONS.has(value as NotificationDestination)
    ? (value as NotificationDestination)
    : null;
}
