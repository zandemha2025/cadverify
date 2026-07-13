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
  /** true → render the HATCHED assumption band (n=0 encoding). */
  hatched?: boolean;
}

export interface NotifState {
  loading: boolean;
  notifs: DerivedNotif[];
  deliveryCount: number | null;
  error: string | null;
}

interface NotificationRow {
  id: string;
  severity: string;
  title: string;
  body: string;
  dest: string;
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

function mapRow(row: NotificationRow): DerivedNotif {
  return {
    id: row.id,
    tone: tone(row.severity),
    title: row.title,
    meta: row.body || "workflow state",
    dest: dest(row.dest),
    hatched: row.metadata?.hatched === true,
  };
}

export async function loadNotifications(): Promise<NotifState> {
  const page = await json<NotificationsPage>(
    "/notifications?status=open&unread=true&limit=25"
  );
  return {
    loading: false,
    notifs: page.notifications.map(mapRow),
    deliveryCount: null,
    error: null,
  };
}

export async function markNotificationRead(id: string): Promise<void> {
  await json(`/notifications/${encodeURIComponent(id)}/read`, { method: "POST" });
}

export async function markAllNotificationsRead(): Promise<number> {
  const res = await json<{ ok: boolean; count: number }>(
    "/notifications/read-all",
    { method: "POST" }
  );
  return res.count;
}
