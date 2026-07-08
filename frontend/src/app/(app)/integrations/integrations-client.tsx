"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileCheck2,
  RefreshCw,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  createIntegrationRun,
  listIntegrationConnectors,
  listIntegrationRuns,
  type IntegrationConnector,
  type IntegrationRun,
} from "@/lib/integrations-api";

const STATUS = {
  passed: "text-emerald-700",
  partial: "text-amber-700",
  failed: "text-destructive",
};

function shortHash(hash: string): string {
  return hash ? `${hash.slice(0, 10)}...` : "—";
}

function dateLabel(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

export function IntegrationsClient() {
  const [connectors, setConnectors] = useState<IntegrationConnector[]>([]);
  const [runs, setRuns] = useState<IntegrationRun[]>([]);
  const [connectorId, setConnectorId] = useState("");
  const [mode, setMode] = useState<"dry_run" | "import">("dry_run");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const selected = useMemo(
    () => connectors.find((c) => c.id === connectorId) ?? connectors[0],
    [connectors, connectorId],
  );

  const refresh = async () => {
    const [nextConnectors, nextRuns] = await Promise.all([
      listIntegrationConnectors(),
      listIntegrationRuns(),
    ]);
    setConnectors(nextConnectors);
    setRuns(nextRuns);
    setConnectorId((current) => current || nextConnectors[0]?.id || "");
  };

  useEffect(() => {
    refresh()
      .catch((err) => toast.error(err instanceof Error ? err.message : "Could not load integrations"))
      .finally(() => setLoading(false));
  }, []);

  const submit = async () => {
    if (!selected || !file) return;
    setRunning(true);
    try {
      const run = await createIntegrationRun({
        connectorId: selected.id,
        mode,
        file,
      });
      setRuns((prev) => [run, ...prev]);
      setFile(null);
      toast.success(mode === "dry_run" ? "Dry-run recorded" : "Import recorded");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Integration run failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Integrations
          </p>
          <h1 className="text-display-l font-semibold text-foreground">
            Offline CSV connector runs
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Run ERP, PLM, and actual-cost CSV exports through the same parsers
            that feed manifests and validation records. Live credentials are not
            used by these connectors.
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => void refresh()}
          disabled={loading}
        >
          <RefreshCw className="mr-2 size-4" />
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {connectors.map((connector) => (
          <Card key={connector.id}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Database className="size-4" />
                {connector.label}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm leading-6 text-muted-foreground">
              <p>{connector.description}</p>
              <div className="grid grid-cols-2 gap-2 font-mono text-xs">
                <span>{connector.source_system}</span>
                <span className="text-right">{connector.source_kind}</span>
                <span>{connector.mode.replace("_", " ")}</span>
                <span className="text-right">
                  raw stored: {connector.raw_payload_stored ? "yes" : "no"}
                </span>
                <span>{connector.file_format.toUpperCase()}</span>
                <span className="text-right">
                  live creds: {connector.live_credentials_required ? "yes" : "no"}
                </span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Upload className="size-5" />
            New connector run
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-[1fr_220px_180px_auto] lg:items-end">
          <label className="space-y-2 text-sm">
            <span className="font-medium text-foreground">Connector</span>
            <select
              value={selected?.id || ""}
              onChange={(e) => setConnectorId(e.target.value)}
              className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
            >
              {connectors.map((connector) => (
                <option key={connector.id} value={connector.id}>
                  {connector.label}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-2 text-sm">
            <span className="font-medium text-foreground">Mode</span>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as "dry_run" | "import")}
              className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
            >
              <option value="dry_run">Dry-run</option>
              <option value="import">Import</option>
            </select>
          </label>

          <label className="space-y-2 text-sm">
            <span className="font-medium text-foreground">CSV</span>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
          </label>

          <Button onClick={() => void submit()} disabled={!file || !selected || running}>
            <FileCheck2 className="mr-2 size-4" />
            {running ? "Running" : "Run"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          {runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {loading ? "Loading..." : "No connector runs yet."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4">Connector</th>
                    <th className="py-2 pr-4">Rows</th>
                    <th className="py-2 pr-4">Mode</th>
                    <th className="py-2 pr-4">File hash</th>
                    <th className="py-2 pr-4">Completed</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td className={`py-3 pr-4 font-medium ${STATUS[run.status]}`}>
                        <span className="inline-flex items-center gap-1.5">
                          {run.status === "failed" ? (
                            <AlertTriangle className="size-4" />
                          ) : (
                            <CheckCircle2 className="size-4" />
                          )}
                          {run.status}
                        </span>
                      </td>
                      <td className="py-3 pr-4">
                        <span className="block font-medium text-foreground">
                          {run.connector_id}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {run.source_system}
                        </span>
                      </td>
                      <td className="py-3 pr-4 font-mono text-xs">
                        {run.rows_valid}/{run.rows_total} valid
                        {run.rows_invalid > 0 && (
                          <span className="ml-2 text-amber-700">
                            {run.rows_invalid} flagged
                          </span>
                        )}
                      </td>
                      <td className="py-3 pr-4">{run.mode}</td>
                      <td className="py-3 pr-4 font-mono text-xs">
                        {shortHash(run.file_sha256)}
                      </td>
                      <td className="py-3 pr-4 text-muted-foreground">
                        {dateLabel(run.completed_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
