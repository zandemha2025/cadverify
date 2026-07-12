import Link from "next/link";
import { BookOpen, KeyRound, TerminalSquare } from "lucide-react";
import { RevealOnceModal } from "@/components/RevealOnceModal";
import { PageHeader } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { createKey, listKeys, revokeKey, rotateKey } from "../../keys/actions";

/**
 * Settings → Developer. API keys are a feature INSIDE the platform now (no
 * longer the front door). This page is reached from the account menu / sidebar;
 * it reuses the session-cookie-proxied key actions, so the keys belong to the
 * logged-in account.
 */

type KeyRow = {
  id: number;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

async function createDefaultKey() {
  "use server";
  await createKey("Default");
}

export default async function DeveloperSettingsPage() {
  const keys = (await listKeys()) as KeyRow[];

  return (
    <div className="space-y-6">
      <RevealOnceModal />

      <PageHeader
        title="Developer"
        subtitle="Create and manage API keys for programmatic access to the ProofShape API."
        actions={
          <form action={createDefaultKey}>
            <Button type="submit">Create key</Button>
          </form>
        }
      />

      <Card className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="font-medium text-foreground">Developer resources</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Read the integration guide, then test authenticated requests against the live OpenAPI contract.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="secondary">
            <Link href="/api-reference"><BookOpen aria-hidden />API reference</Link>
          </Button>
          <Button asChild variant="secondary">
            <a href="/scalar"><TerminalSquare aria-hidden />Open API console</a>
          </Button>
        </div>
      </Card>

      {keys.length === 0 ? (
        <EmptyState
          icon={KeyRound}
          title="No API keys yet"
          description="Create a key to start using the ProofShape API."
          action={
            <form action={createDefaultKey}>
              <Button type="submit">Create key</Button>
            </form>
          }
        />
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Key</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.map((k) => (
                <TableRow key={k.id} className="h-12">
                  <TableCell className="font-medium text-foreground">
                    {k.name}
                  </TableCell>
                  <TableCell className="num text-xs text-muted-foreground">
                    cv_live_{k.prefix}_…
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {k.last_used_at ?? "Never"}
                  </TableCell>
                  <TableCell>
                    <StatusBadge
                      tone={k.revoked_at ? "fail" : "pass"}
                      label={k.revoked_at ? "Revoked" : "Active"}
                      size="sm"
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-2">
                      {!k.revoked_at && (
                        <>
                          <form
                            action={async () => {
                              "use server";
                              await rotateKey(k.id);
                            }}
                          >
                            <Button type="submit" variant="secondary" size="sm">
                              Rotate
                            </Button>
                          </form>
                          <form
                            action={async () => {
                              "use server";
                              await revokeKey(k.id);
                            }}
                          >
                            <Button
                              type="submit"
                              variant="ghost"
                              size="sm"
                              className="text-fail hover:text-fail"
                            >
                              Revoke
                            </Button>
                          </form>
                        </>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}
