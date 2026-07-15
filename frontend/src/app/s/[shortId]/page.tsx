import type { Metadata } from "next";
import Link from "next/link";
import { Box } from "lucide-react";
import { fetchSharedAnalysis } from "@/lib/api";
import type { SharedAnalysis, Issue, ProcessScore } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { verdictTone, verdictLabel } from "@/lib/status";

/* ------------------------------------------------------------------ */
/*  OG Meta Tags for link previews (Slack, email, social)             */
/* ------------------------------------------------------------------ */

export async function generateMetadata({
  params,
}: {
  params: Promise<{ shortId: string }>;
}): Promise<Metadata> {
  const { shortId } = await params;
  try {
    const data = await fetchSharedAnalysis(shortId);
    const processCount = data.process_scores?.length ?? 0;
    return {
      title: `${data.filename} - DFM Analysis`,
      openGraph: {
        title: `${data.filename} - DFM Analysis`,
        description: `Verdict: ${data.verdict} | ${processCount} processes evaluated | ${data.face_count} faces`,
        type: "article",
        siteName: "ProofShape",
      },
      twitter: { card: "summary" },
      robots: { index: false, follow: false },
    };
  } catch {
    return { title: "Shared Analysis - ProofShape" };
  }
}

/* ------------------------------------------------------------------ */
/*  Public shell (no app nav — read-only, but same design language)   */
/* ------------------------------------------------------------------ */

function PublicShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex h-14 max-w-3xl items-center gap-2 px-4">
          <Box className="size-5 text-primary" />
          <span className="font-semibold text-foreground">ProofShape</span>
          <span className="ml-2 text-xs text-muted-foreground">
            Shared analysis · read-only
          </span>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">{children}</main>
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </h2>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="num mt-0.5 text-sm font-semibold text-foreground">{value}</p>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Server Component — read-only public share page                     */
/* ------------------------------------------------------------------ */

export default async function SharedAnalysisPage({
  params,
}: {
  params: Promise<{ shortId: string }>;
}) {
  const { shortId } = await params;

  let data: SharedAnalysis | null = null;
  try {
    data = await fetchSharedAnalysis(shortId);
  } catch {
    /* 404 or network error */
  }

  if (!data) {
    return (
      <PublicShell>
        <Card>
          <CardContent className="py-12 text-center">
            <h1 className="text-xl font-semibold text-foreground">
              Analysis not available
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              This shared analysis is no longer available. It may have been
              revoked by its owner.
            </p>
            <Button asChild className="mt-6">
              <Link href="/">Go to ProofShape</Link>
            </Button>
          </CardContent>
        </Card>
      </PublicShell>
    );
  }

  const sortedIssues = [...(data.universal_issues || [])].sort((a, b) => {
    const order: Record<string, number> = { error: 0, warning: 1, info: 2 };
    return (order[a.severity] ?? 3) - (order[b.severity] ?? 3);
  });

  const sortedProcesses = [...(data.process_scores || [])].sort(
    (a, b) => b.score - a.score,
  );

  const geo = data.geometry || ({} as Record<string, unknown>);

  return (
    <PublicShell>
      {/* Header */}
      <Card tone={verdictTone(data.verdict)}>
        <CardContent className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold text-foreground">
              {data.filename}
            </h1>
            <p className="num mt-1 text-sm text-muted-foreground">
              {data.file_type.toUpperCase()} ·{" "}
              {new Date(data.created_at).toLocaleDateString()} ·{" "}
              {data.duration_ms}ms
            </p>
          </div>
          <StatusBadge
            verdict={data.verdict}
            label={verdictLabel(data.verdict, true)}
          />
        </CardContent>
      </Card>

      {/* Geometry Overview */}
      {"faces" in geo && (
        <section>
          <SectionHeading>Geometry</SectionHeading>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Faces" value={String(data.face_count)} />
            {geo.volume_mm3 != null && (
              <StatCard
                label="Volume"
                value={`${(Number(geo.volume_mm3) / 1000).toFixed(1)} cm3`}
              />
            )}
            {geo.bounding_box_mm && (
              <StatCard
                label="Dimensions"
                value={`${(geo.bounding_box_mm as number[])
                  .map((d: number) => d.toFixed(1))
                  .join(" x ")} mm`}
              />
            )}
            {geo.is_watertight != null && (
              <StatCard
                label="Watertight"
                value={geo.is_watertight ? "Yes" : "No"}
              />
            )}
          </div>
        </section>
      )}

      {/* Issues */}
      {sortedIssues.length > 0 && (
        <section>
          <SectionHeading>Issues ({sortedIssues.length})</SectionHeading>
          <div className="space-y-2">
            {sortedIssues.map((issue: Issue, i: number) => (
              <Card key={i} className="p-3">
                <div className="flex items-center gap-2">
                  <StatusBadge severity={issue.severity} size="sm" />
                  <span className="num text-xs text-muted-foreground">
                    {issue.code}
                  </span>
                </div>
                <p className="mt-1 text-sm text-foreground">{issue.message}</p>
                {issue.fix_suggestion && (
                  <p className="mt-1 text-sm text-primary">
                    {issue.fix_suggestion}
                  </p>
                )}
              </Card>
            ))}
          </div>
        </section>
      )}

      {/* Process Ranking */}
      {sortedProcesses.length > 0 && (
        <section>
          <SectionHeading>Process ranking</SectionHeading>
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Process</TableHead>
                  <TableHead numeric>Score</TableHead>
                  <TableHead>Verdict</TableHead>
                  <TableHead>Material</TableHead>
                  <TableHead>Machine</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedProcesses.map((ps: ProcessScore) => (
                  <TableRow key={ps.process} className="h-11">
                    <TableCell className="font-medium text-foreground">
                      {ps.process}
                    </TableCell>
                    <TableCell numeric>{ps.score}</TableCell>
                    <TableCell>
                      <StatusBadge verdict={ps.verdict} size="sm" />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {ps.recommended_material ?? "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {ps.recommended_machine ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </section>
      )}

      {/* CTA Footer */}
      <Card>
        <CardContent className="text-center">
          <p className="text-sm text-muted-foreground">
            This is a shared analysis from ProofShape.
          </p>
          <Button asChild className="mt-3">
            <Link href="/">View on ProofShape</Link>
          </Button>
        </CardContent>
      </Card>
    </PublicShell>
  );
}
