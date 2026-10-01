"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
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
import { API_BASE } from "@/lib/api-base";
import { ConnectorCredentials } from "./connector-credentials";
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

export function IntegrationsClient({ canManageCredentials = false }: { canManageCredentials?: boolean }) {
  const [connectors, setConnectors] = useState<IntegrationConnector[]>([]);
  const [runs, setRuns] = useState<IntegrationRun[]>([]);
  const [connectorId, setConnectorId] = useState("");
  const [mode, setMode] = useState<"dry_run" | "import">("dry_run");
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const selected = useMemo(
    () => connectors.find((c) => c.id === connectorId) ?? connectors[0],
    [connectors, connectorId],
  );

  const refresh = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [nextConnectors, nextRuns] = await Promise.all([
        listIntegrationConnectors(),
        listIntegrationRuns(),
      ]);
      setConnectors(nextConnectors);
      setRuns(nextRuns);
      setConnectorId((current) => current || nextConnectors[0]?.id || "");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not load integrations";
      setLoadError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const submit = async () => {
    if (!selected || selected.mode !== "offline_csv" || !file || running) return;
    setRunning(true);
    try {
      const run = await createIntegrationRun({
        connectorId: selected.id,
        mode,
        file,
      });
      setRuns((prev) => [run, ...prev]);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      if (run.status === "failed") toast.error("CSV validation failed. See row errors below.");
      else if (run.status === "partial") toast.warning("Some rows failed. See row errors below.");
      else toast.success(mode === "dry_run" ? "Dry-run passed. No data imported." : "Import completed");
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
          <h1 className="text-display-l font-semibold text-foreground">Integration runs</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Run ERP, PLM, and actual-cost CSV exports through the same parsers
            that feed manifests and validation records. CSV runs do not connect
            to vendor systems. Vendor API connections are listed separately below.
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => void refresh()}
          disabled={loading || running}
        >
          <RefreshCw className="mr-2 size-4" />
          Refresh
        </Button>
      </div>
      {loadError && <p role="alert" className="text-sm text-destructive">{loadError} Use Refresh to retry.</p>}

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
              {connector.mode !== "offline_csv" && (
                <p className="font-medium text-amber-700">{connector.id === "windchill_part_bom_readonly" ? "Organization admins can test a connection, preview a complete BOM and import whole-part counts." : "Organization admins can test a connection and preview a SAP BOM explosion. Assembly import is not supported."}</p>
              )}
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
        <CardContent className={`grid gap-4 lg:items-end ${selected?.mode === "offline_csv" ? "lg:grid-cols-[1fr_220px_180px_auto]" : "lg:grid-cols-4"}`}>
          <div className="space-y-2 text-sm">
            <label htmlFor="integration-connector" className="block font-medium text-foreground">
              Connector
            </label>
            <select
              id="integration-connector"
              value={selected?.id || ""}
              onChange={(e) => setConnectorId(e.target.value)}
              disabled={running}
              className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
            >
              {connectors.map((connector) => (
                <option key={connector.id} value={connector.id}>
                  {connector.label}
                </option>
              ))}
            </select>
          </div>

          {selected?.mode === "offline_csv" ? <>
          <div className="space-y-2 text-sm">
            <label htmlFor="integration-mode" className="block font-medium text-foreground">
              Mode
            </label>
            <select
              id="integration-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as "dry_run" | "import")}
              disabled={running}
              className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
            >
              <option value="dry_run">Dry-run</option>
              <option value="import">Import</option>
            </select>
          </div>

          <div className="space-y-2 text-sm">
            <label htmlFor="integration-csv" className="block font-medium text-foreground">
              CSV
            </label>
            <input
              id="integration-csv"
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              disabled={running}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
            {selected.template_endpoint && (
              <a className="underline" href={`${API_BASE}${selected.template_endpoint.replace(/^\/api\/v1/, "")}`} download>
                Download CSV template
              </a>
            )}
          </div>

          <Button onClick={() => void submit()} disabled={!file || !selected || running}>
            <FileCheck2 className="mr-2 size-4" />
            {running ? "Running" : "Run"}
          </Button>
          </> : selected && (
            <>
              <p role="status" className="text-sm text-muted-foreground lg:col-span-3">
                {selected.id === "windchill_part_bom_readonly" ? "Choose a saved connection below to preview and import a Windchill BOM." : "Choose a saved connection below to preview a SAP BOM explosion. Assembly import is not supported. For a CSV export, choose SAP manifest CSV."}
              </p>
              {canManageCredentials ? <ConnectorCredentials key={selected.id} connectorId={selected.id} onRun={() => void refresh()} /> :
                <p className="text-sm text-muted-foreground lg:col-span-4">An organization admin can save and test a vendor connection here.</p>}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          {runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {loading ? "Loading..." : loadError ? "Run history could not be loaded." : "No connector runs yet."}
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
                    <Fragment key={run.id}><tr>
                      <td className={`py-3 pr-4 font-medium ${STATUS[run.status]}`}>
                        <span className="inline-flex items-center gap-1.5">
                          {run.status !== "passed" ? (
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
                    <tr><td colSpan={6} className="pb-4 text-sm">
                      <details open={run.status !== "passed"}>
                        <summary className="cursor-pointer font-medium">Run details{run.filename ? ` · ${run.filename}` : ""}</summary>
                        <p className="mt-2 text-muted-foreground">
                          {run.mode === "dry_run" ? "Dry-run only. No data imported." : `${run.imported_count} imported · ${run.updated_count} updated · ${run.skipped_count} skipped`}
                        </p>
                        {run.errors.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5 text-destructive">
                          {run.errors.map((error, index) => <li key={index}>
                            {error.line != null ? `Line ${error.line}: ` : error.index != null ? `Record ${error.index}: ` : ""}{error.reason}
                          </li>)}
                        </ul>}
                        {run.status === "failed" && run.errors.length === 0 && <p className="mt-2 text-destructive">No valid rows were found. Check your CSV against the template.</p>}
                      </details>
                    </td></tr></Fragment>
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
