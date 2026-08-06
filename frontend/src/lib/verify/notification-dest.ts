export type NotificationDestination = "records" | "calibration" | "verify";

const DESTINATIONS = new Set<NotificationDestination>([
  "records",
  "calibration",
  "verify",
]);

export function notificationHref(dest: NotificationDestination): string {
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
