/**
 * Durable notifications data layer for the Verify surface.
 *
 * Notifications are now first-class backend rows emitted beside domain
 * mutations. Audit remains the compliance record; this inbox is workflow state.
 */
import { API_BASE } from "@/lib/api-base";
import type { NotificationDestination } from "./notification-dest";

/** Where a row navigates in the Verify shell (screen keys). */
export type NotifDest = NotificationDestination;

/** Visual tone → status colour (pass/cond) or neutral info. */
export type NotifTone = "pass" | "cond" | "info";

export interface DerivedNotif {
  id: string;
  tone: NotifTone;
  title: string;
  /** mono sub-line — every value is emitted by the backend row. */
  meta: string;
  dest: NotifDest;
  isRead: boolean;
  readAt: string | null;
  isDismissed: boolean;
  dismissedAt: string | null;
  /** true → render the HATCHED assumption band (n=0 encoding). */
  hatched?: boolean;
}

export interface NotifState {
  loading: boolean;
  notifs: DerivedNotif[];
  deliveryCount: number | null;
  error: string | null;
}

export interface NotificationRow {
  id: string;
  severity: string;
  title: string;
  body: string;
  dest: string;
  is_read: boolean;
  read_at: string | null;
  is_dismissed: boolean;
  dismissed_at: string | null;
  metadata?: Record<string, unknown>;
}

interface NotificationsPage {
  notifications: NotificationRow[];
  next_cursor: string | null;
  has_more: boolean;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail =
      (body && (body.detail || body.message)) || `Request failed (${res.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

function tone(severity: string): NotifTone {
  return severity === "pass" || severity === "cond" ? severity : "info";
}

function dest(value: string): NotifDest {
  return value === "records" || value === "calibration" || value === "verify"
    ? value
    : "verify";
}

export function mapNotificationRow(row: NotificationRow): DerivedNotif {
  return {
    id: row.id,
    tone: tone(row.severity),
    title: row.title,
    meta: row.body || "workflow state",
    dest: dest(row.dest),
    isRead: row.is_read,
    readAt: row.read_at,
    isDismissed: row.is_dismissed,
    dismissedAt: row.dismissed_at,
    hatched: row.metadata?.hatched === true,
  };
}

export async function loadNotifications({
  unread = true,
  dismissed = false,
}: {
  unread?: boolean;
  dismissed?: boolean;
} = {}): Promise<NotifState> {
  const query = new URLSearchParams({
    status: "open",
    unread: String(unread),
    dismissed: String(dismissed),
    limit: "100",
  });
  const page = await json<NotificationsPage>(
    `/notifications?${query.toString()}`
  );
  return {
    loading: false,
    notifs: page.notifications.map(mapNotificationRow),
    deliveryCount: null,
    error: null,
  };
}

async function mutateNotification(
  id: string,
  action: "read" | "dismiss" | "restore"
): Promise<DerivedNotif> {
  const result = await json<{ ok: boolean; notification: NotificationRow }>(
    `/notifications/${encodeURIComponent(id)}/${action}`,
    { method: "POST" }
  );
  return mapNotificationRow(result.notification);
}

export function markNotificationRead(id: string): Promise<DerivedNotif> {
  return mutateNotification(id, "read");
}

export function dismissNotification(id: string): Promise<DerivedNotif> {
  return mutateNotification(id, "dismiss");
}

export function restoreNotification(id: string): Promise<DerivedNotif> {
  return mutateNotification(id, "restore");
}

export async function markAllNotificationsRead(): Promise<{
  count: number;
  readAt: string | null;
}> {
  const res = await json<{ ok: boolean; count: number; read_at: string | null }>(
    "/notifications/read-all",
    { method: "POST" }
  );
  return { count: res.count, readAt: res.read_at };
}
