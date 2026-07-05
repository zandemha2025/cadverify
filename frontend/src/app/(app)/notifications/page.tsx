import type { Metadata } from "next";
import Link from "next/link";
import { Bell, CheckCircle2, Clock3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Notifications - CadVerify",
  robots: { index: false, follow: false },
};

export default function NotificationsPage() {
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
            This inbox is intentionally quiet until the notification backend and webhook delivery log are live. Today, action states are computed inside the Verify shell from real machines, governance, and ground-truth reads.
          </p>
        </div>
        <Button asChild>
          <Link href="/verify">Open Verify</Link>
        </Button>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell /> Needs action
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">
            Declare-floor, proposed-rate, and send-actuals nudges are derived in the product shell. No message is fabricated into this standalone inbox yet.
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock3 /> Delivery log
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">
            Webhook delivery storage is still in development, so there are no fake retries, timestamps, or success counts here.
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle2 /> Source of truth
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">
            The audit log and verification records remain the canonical record until a dedicated notifications service ships.
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
