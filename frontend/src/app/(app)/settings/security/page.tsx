import { LockKeyhole } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SecuritySettingsClient } from "./security-settings-client";

export default function SecuritySettingsPage() {
  const authMode = (process.env.AUTH_MODE || "password").trim().toLowerCase();
  if (authMode === "password" || authMode === "hybrid") {
    return <SecuritySettingsClient />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Security"
        subtitle="Authentication is managed by your organization."
      />
      <Card className="max-w-2xl">
        <CardHeader>
          <div className="flex items-center gap-2">
            <LockKeyhole className="size-4 text-primary" />
            <CardTitle>Enterprise identity</CardTitle>
          </div>
          <CardDescription>
            Password setup is disabled in this environment. Sign-in policy,
            multifactor authentication, and recovery are controlled by the
            approved identity provider.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Contact your organization administrator for access or recovery.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
