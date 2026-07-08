"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Bell, CheckCircle2, Clock3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  loadNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type DerivedNotif,
  type NotifState,
} from "@/lib/verify/notifications-api";

const TONE: Record<DerivedNotif["tone"], string> = {
  pass: "text-emerald-700",
  cond: "text-amber-700",
  info: "text-foreground",
};

export function NotificationsClient() {
  const [state, setState] = useState<NotifState>({
    loading: true,
    notifs: [],
    deliveryCount: null,
    error: null,
  });

  useEffect(() => {
    let live = true;
    loadNotifications().then(
      (s) => live && setState(s),
      (e) =>
        live &&
        setState({
          loading: false,
          notifs: [],
          deliveryCount: null,
          error: e instanceof Error ? e.message : "could not load notifications",
        })
    );
    return () => {
      live = false;
    };
  }, []);

  const markAll = () => {
    markAllNotificationsRead().catch(() => {});
    setState((s) => ({ ...s, notifs: [] }));
  };

  const markOne = (id: string) => {
    markNotificationRead(id).catch(() => {});
  };

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
            integration events.
          </p>
        </div>
        <div className="flex gap-2">
          {state.notifs.length > 0 && (
            <Button variant="secondary" onClick={markAll}>
              Mark all read
            </Button>
          )}
          <Button asChild>
            <Link href="/verify">Open Verify</Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell /> Needs action
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-6 text-muted-foreground">
            {state.loading ? (
              <p>Reading current states...</p>
            ) : state.error ? (
              <p className="text-destructive">{state.error}</p>
            ) : state.notifs.length === 0 ? (
              <p>You&apos;re all caught up.</p>
            ) : (
              state.notifs.map((n) => (
                <Link
                  key={n.id}
                  href="/verify"
                  onClick={() => markOne(n.id)}
                  className="block rounded-md border border-border p-3 transition-colors hover:bg-muted"
                >
                  <span className={`block font-medium ${TONE[n.tone]}`}>
                    {n.title}
                  </span>
                  <span className="mt-1 block font-mono text-xs text-muted-foreground">
                    {n.meta}
                  </span>
                </Link>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock3 /> Inbox feed
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">
            {state.deliveryCount == null
              ? "New workflow states appear here as your organization verifies parts and reviews governed changes."
              : state.deliveryCount === 0
                ? "No webhook deliveries recorded yet."
                : `${state.deliveryCount} latest webhook delivery row${
                    state.deliveryCount === 1 ? "" : "s"
                  } included above.`}
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
            canonical record.
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
