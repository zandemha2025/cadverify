"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArchiveRestore, Bell, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  dismissNotification,
  loadNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  restoreNotification,
  type DerivedNotif,
} from "@/lib/verify/notifications-api";
import { notificationHref } from "@/lib/verify/notification-dest";

const TONE: Record<DerivedNotif["tone"], string> = {
  pass: "text-emerald-700",
  cond: "text-amber-700",
  info: "text-foreground",
};

interface InboxState {
  loading: boolean;
  active: DerivedNotif[];
  dismissed: DerivedNotif[];
  error: string | null;
  actionError: string | null;
  busy: string | null;
}

const INITIAL_STATE: InboxState = {
  loading: true,
  active: [],
  dismissed: [],
  error: null,
  actionError: null,
  busy: null,
};

function dateLabel(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

async function readInbox() {
  const [active, dismissed] = await Promise.all([
    loadNotifications({ unread: false, dismissed: false }),
    loadNotifications({ unread: false, dismissed: true }),
  ]);
  return { active: active.notifs, dismissed: dismissed.notifs };
}

export function NotificationsClient() {
  const router = useRouter();
  const [state, setState] = useState<InboxState>(INITIAL_STATE);

  useEffect(() => {
    let live = true;
    readInbox().then(
      ({ active, dismissed }) => {
        if (live) {
          setState({
            loading: false,
            active,
            dismissed,
            error: null,
            actionError: null,
            busy: null,
          });
        }
      },
      (error) => {
        if (live) {
          setState((current) => ({
            ...current,
            loading: false,
            error:
              error instanceof Error
                ? error.message
                : "Could not load notifications",
          }));
        }
      }
    );
    return () => {
      live = false;
    };
  }, []);

  async function retryLoad() {
    setState((current) => ({
      ...current,
      loading: true,
      error: null,
      actionError: null,
    }));
    try {
      const { active, dismissed } = await readInbox();
      setState({
        loading: false,
        active,
        dismissed,
        error: null,
        actionError: null,
        busy: null,
      });
    } catch (error) {
      setState((current) => ({
        ...current,
        loading: false,
        error:
          error instanceof Error ? error.message : "Could not load notifications",
      }));
    }
  }

  async function markAll() {
    setState((current) => ({ ...current, busy: "all", actionError: null }));
    try {
      const result = await markAllNotificationsRead();
      setState((current) => ({
        ...current,
        busy: null,
        active: current.active.map((notification) => ({
          ...notification,
          isRead: true,
          readAt: result.readAt,
        })),
      }));
    } catch (error) {
      setState((current) => ({
        ...current,
        busy: null,
        actionError:
          error instanceof Error ? error.message : "Notifications were not updated",
      }));
    }
  }

  async function openOne(notification: DerivedNotif) {
    const busy = `open:${notification.id}`;
    setState((current) => ({ ...current, busy, actionError: null }));
    try {
      const updated = await markNotificationRead(notification.id);
      setState((current) => ({
        ...current,
        busy: null,
        active: current.active.map((item) =>
          item.id === notification.id ? updated : item
        ),
      }));
    } catch {
      // Opening the source remains available during an inbox outage. The next
      // inbox load truthfully reflects whether the read transition persisted.
      setState((current) => ({ ...current, busy: null }));
    }
    router.push(notificationHref(notification.dest));
  }

  async function dismiss(id: string) {
    setState((current) => ({ ...current, busy: id, actionError: null }));
    try {
      const updated = await dismissNotification(id);
      setState((current) => ({
        ...current,
        busy: null,
        active: current.active.filter((notification) => notification.id !== id),
        dismissed: [
          updated,
          ...current.dismissed.filter((notification) => notification.id !== id),
        ],
      }));
    } catch (error) {
      setState((current) => ({
        ...current,
        busy: null,
        actionError:
          error instanceof Error ? error.message : "Notification was not dismissed",
      }));
    }
  }

  async function restore(id: string) {
    setState((current) => ({ ...current, busy: id, actionError: null }));
    try {
      const updated = await restoreNotification(id);
      setState((current) => ({
        ...current,
        busy: null,
        dismissed: current.dismissed.filter(
          (notification) => notification.id !== id
        ),
        active: [
          updated,
          ...current.active.filter((notification) => notification.id !== id),
        ],
      }));
    } catch (error) {
      setState((current) => ({
        ...current,
        busy: null,
        actionError:
          error instanceof Error ? error.message : "Notification was not restored",
      }));
    }
  }

  const unreadCount = state.active.filter((notification) => !notification.isRead)
    .length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Inbox
          </p>
          <h1 className="text-display-l font-semibold text-foreground">
            Notifications
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Durable workflow rows emitted by verification, governance, and
            integration events. Dismissal changes only your inbox.
          </p>
        </div>
        <div className="flex gap-2">
          {unreadCount > 0 && (
            <Button
              variant="secondary"
              loading={state.busy === "all"}
              onClick={() => void markAll()}
            >
              Mark all read
            </Button>
          )}
          <Button asChild>
            <Link href="/verify">Open Verify</Link>
          </Button>
        </div>
      </div>

      {state.actionError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
        >
          <span>Nothing changed — {state.actionError}</span>
          <Button variant="secondary" size="sm" onClick={() => void retryLoad()}>
            Reload inbox
          </Button>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell /> Inbox ({state.active.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-6 text-muted-foreground">
            {state.loading ? (
              <p>Reading current states...</p>
            ) : state.error ? (
              <div className="space-y-3" role="alert">
                <p className="text-destructive">{state.error}</p>
                <Button variant="secondary" size="sm" onClick={() => void retryLoad()}>
                  Try again
                </Button>
              </div>
            ) : state.active.length === 0 ? (
              <p>You&apos;re all caught up.</p>
            ) : (
              state.active.map((notification) => (
                <article
                  key={notification.id}
                  data-notification-id={notification.id}
                  data-read-at={notification.readAt ?? ""}
                  className="rounded-md border border-border p-3"
                >
                  <p className={`font-medium ${TONE[notification.tone]}`}>
                    {notification.title}
                  </p>
                  <p className="mt-1 break-words font-mono text-xs text-muted-foreground">
                    {notification.meta}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {notification.isRead
                      ? `Read ${dateLabel(notification.readAt)}`
                      : "Unread"}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button asChild variant="secondary" size="sm">
                      <Link
                        href={notificationHref(notification.dest)}
                        aria-label={`Open notification: ${notification.title}`}
                        aria-busy={state.busy === `open:${notification.id}`}
                        onClick={(event) => {
                          if (
                            event.button !== 0 ||
                            event.metaKey ||
                            event.ctrlKey ||
                            event.shiftKey ||
                            event.altKey
                          ) {
                            void markNotificationRead(notification.id).catch(() => undefined);
                            return;
                          }
                          event.preventDefault();
                          if (state.busy) return;
                          void openOne(notification);
                        }}
                      >
                        {state.busy === `open:${notification.id}` ? "Opening…" : "Open"}
                      </Link>
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      loading={state.busy === notification.id}
                      aria-label={`Dismiss notification: ${notification.title}`}
                      onClick={() => void dismiss(notification.id)}
                    >
                      Dismiss
                    </Button>
                  </div>
                </article>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ArchiveRestore /> Dismissed ({state.dismissed.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-6 text-muted-foreground">
            {!state.loading && !state.error && state.dismissed.length === 0 ? (
              <p>No dismissed notifications.</p>
            ) : (
              state.dismissed.map((notification) => (
                <article
                  key={notification.id}
                  data-notification-id={notification.id}
                  data-dismissed-at={notification.dismissedAt ?? ""}
                  className="rounded-md border border-border p-3"
                >
                  <p className={`font-medium ${TONE[notification.tone]}`}>
                    {notification.title}
                  </p>
                  <p className="mt-1 break-words font-mono text-xs">
                    {notification.meta}
                  </p>
                  <p className="mt-2 text-xs">
                    Dismissed {dateLabel(notification.dismissedAt)}
                  </p>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="mt-3"
                    loading={state.busy === notification.id}
                    aria-label={`Restore notification: ${notification.title}`}
                    onClick={() => void restore(notification.id)}
                  >
                    Restore
                  </Button>
                </article>
              ))
            )}
            <p className="text-xs">
              Restore returns a notification to your inbox with its prior read
              state.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle2 /> Source of truth
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">
            Audit log, verification records, and webhook delivery rows remain the
            canonical record. Reading or dismissing an inbox item never changes
            those records for your organization.
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
