"use client";

/**
 * Imports (board M3): connectors, CSV runs (dry run first, import confirmed),
 * the run history with errors by line, and for live read-only connectors the
 * organization admin's saved connections: save, test, revoke (confirmed), and
 * the way into a BOM preview.
 */
import * as React from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api-base";
import {
  createIntegrationRun,
  listConnectorCredentials,
  listIntegrationConnectors,
  listIntegrationRuns,
  probeConnectorCredential,
  revokeConnectorCredential,
  saveConnectorCredential,
  type ConnectorAuthType,
  type ConnectorCredentialProfile,
  type ConnectorProbe,
  type IntegrationConnector,
  type IntegrationRun,
} from "@/lib/integrations-api";
import { R } from "../routes";
import { Chip, Content, Empty, Loading, PageHead, Panel, Sheet, cx } from "../ui";
import { ManyWorld, PilotGate, errorText, revealSheetOnPhone, saveBlob, useManyTabs, usePilotAccess, useToast, whenLabel } from "./common";

export const IMPORTS_GATE = {
  title: "Imports",
  slot: "ERP, PLM and BOM data",
  tab: 2,
  features: [
    { title: "CSV dry run", text: "Errors by line before anything is saved", tone: "#ECEEF1" },
    { title: "Live read-only connectors", text: "SAP S/4HANA and PTC Windchill, read only", tone: "#E8EEFB" },
    { title: "BOM preview", text: "Read an assembly; import whole-part counts", tone: "#E3F1E8" },
  ],
  inputs: ["Inputs: CSV exports", "Or a read-only service account"],
};

const AUTH_FIELDS: Record<ConnectorAuthType, { name: string; label: string; type?: string; optional?: boolean; defaultValue?: string }[]> = {
  bearer: [{ name: "token", label: "Access token", type: "password" }],
  basic: [
    { name: "username", label: "Username" },
    { name: "password", label: "Password", type: "password" },
  ],
  oauth2_client_credentials: [
    { name: "token_url", label: "Token endpoint URL", type: "url" },
    { name: "client_id", label: "Client ID" },
    { name: "client_secret", label: "Client secret", type: "password" },
    { name: "scope", label: "Scope (optional)", optional: true },
  ],
  api_key: [
    { name: "header_name", label: "API key header", defaultValue: "X-API-Key" },
    { name: "api_key", label: "API key", type: "password" },
  ],
};

/** The connector as the API sends it; the shared type omits the API name and version. */
type Conn = IntegrationConnector & { api_name?: string | null; api_version?: string | null };

const isLive = (c: IntegrationConnector) => c.mode !== "offline_csv";
const isSap = (id: string) => id.startsWith("sap_");

function shortLabel(c: IntegrationConnector): string {
  return c.label.replace(/\s+read-only$/i, "").replace("Quote/actuals CSV", "Quotes and actuals CSV");
}

const RUN_STATUS: Record<string, ["ok" | "warn" | "bad", string]> = { passed: ["ok", "Passed"], partial: ["warn", "Partial"], failed: ["bad", "Failed"] };

function runSummary(run: IntegrationRun): string {
  if (run.mode === "dry_run") return `Dry run: ${run.rows_valid} of ${run.rows_total} rows valid. Nothing saved.`;
  return `${run.imported_count} imported · ${run.updated_count} updated · ${run.skipped_count} skipped`;
}

export function ImportsScreen() {
  const [access] = usePilotAccess();
  const tabs = useManyTabs();
  const [toastNode, toast] = useToast();
  const [connectors, setConnectors] = React.useState<IntegrationConnector[] | null>(null);
  const [connErr, setConnErr] = React.useState<string | null>(null);
  const [runs, setRuns] = React.useState<IntegrationRun[] | null>(null);
  const [runsErr, setRunsErr] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [admin, setAdmin] = React.useState<boolean | null>(null);
  const [orgErr, setOrgErr] = React.useState(false);
  const [sel, setSel] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState<Record<string, number>>({});

  const loadOrg = React.useCallback(() => {
    setOrgErr(false);
    fetch(`${API_BASE}/orgs`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((b: { active_org_id?: string; organizations?: { org_id: string; org_role: string }[] }) => {
        const org = b.organizations?.find((o) => o.org_id === b.active_org_id);
        if (!org) throw new Error("no active org");
        setAdmin(org.org_role === "admin");
      })
      .catch(() => {
        setOrgErr(true);
        setAdmin(false);
      });
  }, []);

  const loadRuns = React.useCallback(async () => {
    setRefreshing(true);
    setRunsErr(null);
    try {
      setRuns(await listIntegrationRuns());
    } catch (e) {
      setRunsErr(errorText(e, "Runs didn’t load."));
    } finally {
      setRefreshing(false);
    }
  }, []);

  const loadConnectors = React.useCallback(async () => {
    setConnErr(null);
    try {
      const c = await listIntegrationConnectors();
      setConnectors(c);
      setSel((cur) => cur ?? c.find(isLive)?.id ?? c[0]?.id ?? null);
    } catch (e) {
      setConnErr(errorText(e, "Connectors didn’t load."));
    }
  }, []);

  React.useEffect(() => {
    loadOrg();
    void loadConnectors();
    void loadRuns();
  }, [loadOrg, loadConnectors, loadRuns]);

  // Saved-connection counts for the live connectors' chips (admins only can read them).
  React.useEffect(() => {
    if (!admin || !connectors) return;
    for (const c of connectors.filter(isLive)) {
      listConnectorCredentials(c.id).then(
        (p) => setSaved((s) => ({ ...s, [c.id]: p.filter((x) => !x.revoked_at).length })),
        () => {},
      );
    }
  }, [admin, connectors]);

  if (access === "gated") return <PilotGate {...IMPORTS_GATE} />;

  const list = connectors ?? [];
  const live = list.filter(isLive);
  const ready = list.filter((c) => !isLive(c) || (saved[c.id] ?? 0) > 0).length;
  const need = live.filter((c) => !(saved[c.id] ?? 0)).length;
  const selected = list.find((c) => c.id === sel) ?? null;
  const byId = new Map(list.map((c) => [c.id, c]));

  return (
    <ManyWorld label="Imports">
      <PageHead
        title="Imports"
        meta={
          connectors
            ? [
                <span key="n">
                  <b>{list.length}</b> connectors
                </span>,
                <span key="r">
                  <b>{ready}</b> ready
                </span>,
                <span key="c">
                  <b>{need}</b> need credentials
                </span>,
                "Read only",
              ]
            : ["Loading"]
        }
        tabs={tabs}
        tabsLabel="Many parts"
      />
      <Content>
        {orgErr ? (
          <Panel>
            <Empty
              title="Organization access unavailable"
              actions={
                <button className="btn sm" type="button" onClick={loadOrg}>
                  Try again
                </button>
              }
            >
              Your organization or role couldn’t be confirmed. CSV runs still work; saved connections need an admin.
            </Empty>
          </Panel>
        ) : null}
        <Panel title="Connectors" note={connectors ? String(list.length) : undefined}>
          {connErr ? (
            <Empty
              title="Connectors didn’t load"
              actions={
                <button className="btn sm" type="button" onClick={() => void loadConnectors()}>
                  Try again
                </button>
              }
            >
              {connErr}
            </Empty>
          ) : !connectors ? (
            <Loading rows={4} label="Loading connectors" />
          ) : (
            <div className="list" role="list" aria-label="Connectors">
              {list.map((c) => {
                const n = saved[c.id] ?? 0;
                const state = !isLive(c) ? ["ok", "Ready"] : n ? ["ok", n === 1 ? "Saved" : `${n} saved`] : ["unk", "Not connected"];
                return (
                  <div role="listitem" key={c.id}>
                    <button type="button" className={cx("lrow", sel === c.id && "on")} aria-pressed={sel === c.id} onClick={() => {
                        setSel(c.id);
                        revealSheetOnPhone("Connector");
                      }}>
                      <span className={cx("ico", isLive(c) && "live")} aria-hidden="true">
                        {isLive(c) ? "Live" : "CSV"}
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <b>{shortLabel(c)}</b>
                        <small>{isLive(c) ? `Live · read only · ${c.source_system}` : `${c.description.replace(/\.$/, "")} · ${c.source_system}`}</small>
                      </span>
                      <span>
                        <Chip tone={state[0] as "ok" | "unk"}>{state[1]}</Chip>
                      </span>
                      <span className="c" style={{ fontWeight: 500, color: "var(--ink3)", fontSize: 12.5 }}>
                        {isLive(c) ? "Live" : "File"}
                      </span>
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
        <Panel title="Import steps" note="Dry run first">
          <div className="flow">
            <div className="fs">
              <i>1</i>
              <b>Read</b>Rows from the file or system. Nothing saved.
            </div>
            <div className="fs">
              <i>2</i>
              <b>Match</b>Each row to a part, program and yearly volume. Errors listed by line.
            </div>
            <div className="fs">
              <i>3</i>
              <b>Save</b>After review. Parts appear in Parts; quotes and actuals in Your shop.
            </div>
          </div>
        </Panel>
        <Panel
          title="Runs"
          actions={
            <span style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span className="num">{runs?.length ?? ""}</span>
              <button className="btn sm" type="button" onClick={() => void loadRuns()} disabled={refreshing}>
                {refreshing ? "Refreshing…" : "Refresh"}
              </button>
            </span>
          }
        >
          {runsErr && !runs ? (
            <Empty
              title="Runs didn’t load"
              actions={
                <button className="btn sm" type="button" onClick={() => void loadRuns()}>
                  Try again
                </button>
              }
            >
              Imported parts are unchanged. {runsErr}
            </Empty>
          ) : !runs ? (
            <Loading rows={2} label="Loading runs" />
          ) : runs.length === 0 ? (
            <Empty
              title="No runs yet"
              actions={
                <button
                  className="btn sm"
                  type="button"
                  onClick={() => {
                    const first = list.find((c) => !isLive(c));
                    if (first) setSel(first.id);
                  }}
                >
                  Start dry run
                </button>
              }
            >
              A dry run creates the first one. Each run lists its rows, errors by line, and file hash.
            </Empty>
          ) : (
            <div className="runs" role="list" aria-label="Runs">
              {runs.map((run) => {
                const [tone, label] = RUN_STATUS[run.status] ?? ["unk", run.status];
                const c = byId.get(run.connector_id);
                return (
                  <div className="rr" role="listitem" key={run.id}>
                    <div className="top">
                      <Chip tone={tone as "ok"}>{label}</Chip>
                      <b style={{ fontWeight: 600 }}>{c ? shortLabel(c) : run.connector_id}</b>
                      <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>
                        {run.mode === "dry_run" ? "Dry run" : "Import"} · {run.rows_valid}/{run.rows_total} valid
                        {run.rows_invalid ? ` · ${run.rows_invalid} flagged` : ""} · {whenLabel(run.completed_at ?? run.created_at)}
                      </span>
                      <span className="mm" style={{ marginLeft: "auto", color: "var(--ink3)" }} title={run.file_sha256}>
                        {run.file_sha256 ? `${run.file_sha256.slice(0, 10)}…` : "—"}
                      </span>
                    </div>
                    <details open={run.status !== "passed"}>
                      <summary>Run details{run.filename ? ` · ${run.filename}` : ""}</summary>
                      <p style={{ margin: "6px 0 0", color: "var(--ink2)", fontSize: 13 }}>{runSummary(run)}</p>
                      {run.errors.length ? (
                        <ul>
                          {run.errors.map((e, i) => (
                            <li key={i}>
                              {e.line != null ? `Line ${e.line}: ` : e.index != null ? `Record ${e.index}: ` : ""}
                              {e.reason}
                            </li>
                          ))}
                        </ul>
                      ) : run.status === "failed" ? (
                        <p style={{ margin: "6px 0 0", color: "var(--bad)", fontSize: 12.5 }}>No valid rows. Check the CSV against the template.</p>
                      ) : null}
                    </details>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
      </Content>
      {selected ? (
        isLive(selected) ? (
          <LiveSheet
            key={selected.id}
            connector={selected}
            admin={admin}
            onSaved={(n) => setSaved((s) => ({ ...s, [selected.id]: n }))}
            toast={toast}
          />
        ) : (
          <CsvSheet key={selected.id} connector={selected} onRun={(run) => setRuns((r) => [run, ...(r ?? [])])} toast={toast} />
        )
      ) : (
        <Sheet label="Connector">
          <div className="top">
            <h2 className="stitle">Connector</h2>
            <p className="smeta">{connErr ? "Connectors didn’t load" : "Loading"}</p>
          </div>
        </Sheet>
      )}
      {toastNode}
    </ManyWorld>
  );
}

/* ------------------------------------------------------------------ */
/*  CSV connector                                                      */
/* ------------------------------------------------------------------ */

function CsvSheet({ connector, onRun, toast }: { connector: IntegrationConnector; onRun: (r: IntegrationRun) => void; toast: (t: string) => void }) {
  const [file, setFile] = React.useState<File | null>(null);
  const [mode, setMode] = React.useState<"dry_run" | "import">("dry_run");
  const [asking, setAsking] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [tplBusy, setTplBusy] = React.useState(false);
  const input = React.useRef<HTMLInputElement>(null);
  const realCosts = connector.source_kind === "ground_truth";

  const template = async () => {
    if (!connector.template_endpoint || tplBusy) return;
    setTplBusy(true);
    try {
      const res = await fetch(`${API_BASE}${connector.template_endpoint.replace(/^\/api\/v1/, "")}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`The template didn’t download (${res.status}).`);
      const name = /filename="?([^";]+)"?/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? `${connector.id}-template.csv`;
      saveBlob(await res.blob(), name);
      toast(`Downloaded ${name}`);
    } catch (e) {
      toast(errorText(e, "The template didn’t download."));
    } finally {
      setTplBusy(false);
    }
  };

  const run = async () => {
    if (!file || running) return;
    if (mode === "import" && !asking) {
      setAsking(true);
      return;
    }
    setAsking(false);
    setRunning(true);
    setResult(null);
    try {
      const r = await createIntegrationRun({ connectorId: connector.id, mode, file });
      onRun(r);
      const ok = r.status !== "failed";
      setResult({ ok, text: `${r.status === "passed" ? "Passed" : r.status === "partial" ? "Partly passed" : "Failed"}. ${runSummary(r)}${r.errors.length ? ` ${r.errors.length} ${r.errors.length === 1 ? "error" : "errors"} by line in Runs.` : ""}` });
      toast(mode === "dry_run" ? "Dry run done. Results in Runs." : "Import done. Results in Runs.");
      setFile(null);
      if (input.current) input.current.value = "";
    } catch (e) {
      setResult({ ok: false, text: errorText(e, "The run didn’t finish.") });
    } finally {
      setRunning(false);
    }
  };

  return (
    <Sheet label="Connector">
      <div className="top">
        <h2 className="stitle">{shortLabel(connector)}</h2>
        <p className="smeta">CSV file · ready · {connector.source_system}</p>
      </div>
      <div className="scroll">
        <div className="swap">
          <div className="gh">
            <span>File</span>
            <span>CSV</span>
          </div>
          <p style={{ margin: "0 12px 8px", color: "var(--ink2)", fontSize: 13.5 }}>
            {connector.description}
            {realCosts ? " Imported as real costs in Your shop." : " Parts appear in Parts."}
          </p>
          <div style={{ display: "flex", gap: 8, padding: "4px 12px 10px", flexWrap: "wrap" }}>
            {connector.template_endpoint ? (
              <button className="btn sm" type="button" onClick={() => void template()} disabled={tplBusy}>
                {tplBusy ? "Downloading…" : "Download template"}
              </button>
            ) : null}
            <button className="btn sm" type="button" onClick={() => input.current?.click()} disabled={running}>
              {file ? `${file.name} · change` : "Choose CSV"}
            </button>
            <input
              ref={input}
              type="file"
              accept=".csv,text/csv"
              aria-label={`CSV for ${shortLabel(connector)}`}
              tabIndex={-1}
              style={{ display: "none" }}
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setAsking(false);
                setResult(null);
              }}
            />
          </div>
          <div className="gh">
            <span>Run as</span>
            <span />
          </div>
          <div style={{ padding: "4px 12px" }}>
            <span className="seg" role="group" aria-label="Run as">
              <button type="button" className={cx(mode === "dry_run" && "on")} aria-pressed={mode === "dry_run"} onClick={() => { setMode("dry_run"); setAsking(false); }}>
                Dry run
              </button>
              <button type="button" className={cx(mode === "import" && "on")} aria-pressed={mode === "import"} onClick={() => setMode("import")}>
                Import
              </button>
            </span>
          </div>
          <p style={{ margin: "10px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
            {mode === "dry_run" ? "Dry run saves nothing." : realCosts ? "Saves matched records as real costs. Run a dry run first." : "Saves matched parts. Run a dry run first."}
          </p>
          <div style={{ padding: 12, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn ink" type="button" aria-disabled={!file || running} onClick={() => void run()}>
              {running ? "Running…" : mode === "dry_run" ? "Start dry run" : "Import"}
            </button>
            {!file ? <span className="fh">Choose a CSV first</span> : null}
          </div>
          {asking && file ? (
            <div className="confirm" role="alertdialog" aria-label="Import" style={{ margin: "0 12px" }}>
              <b>Import {file.name}?</b>
              <span>
                {realCosts ? "Matched records are saved as real costs." : "Matched parts are saved and existing ones updated."} Run a dry run first to see errors by line.
              </span>
              <span style={{ display: "flex", gap: 8 }}>
                <button className="btn ink sm" type="button" onClick={() => void run()} autoFocus>
                  Import
                </button>
                <button className="btn sm" type="button" onClick={() => setAsking(false)}>
                  Cancel
                </button>
              </span>
            </div>
          ) : null}
          {result ? (
            <p className={cx("res", !result.ok && "bad")} role={result.ok ? "status" : "alert"} style={{ margin: "8px 12px 0" }}>
              {result.text}
            </p>
          ) : null}
        </div>
        <p style={{ margin: "12px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
          {connector.raw_payload_stored ? "Raw files are kept with the run." : "Raw files aren’t stored after import."}
        </p>
      </div>
    </Sheet>
  );
}

/* ------------------------------------------------------------------ */
/*  Live connector                                                     */
/* ------------------------------------------------------------------ */

function LiveSheet({
  connector,
  admin,
  onSaved,
  toast,
}: {
  connector: Conn;
  admin: boolean | null;
  onSaved: (activeCount: number) => void;
  toast: (t: string) => void;
}) {
  const sap = isSap(connector.id);
  const [profiles, setProfiles] = React.useState<ConnectorCredentialProfile[] | null>(null);
  const [profErr, setProfErr] = React.useState<string | null>(null);
  const [reload, setReload] = React.useState(0);
  const [auth, setAuth] = React.useState<ConnectorAuthType>("bearer");
  const [busy, setBusy] = React.useState("");
  const [formErr, setFormErr] = React.useState<string | null>(null);
  const [probes, setProbes] = React.useState<Record<string, ConnectorProbe | { error: string }>>({});
  const [confirm, setConfirm] = React.useState<string | null>(null);
  const urlPh = sap ? "https://your-sap-host" : "https://your-windchill-host/Windchill/servlet/odata/ProdMgmt";

  React.useEffect(() => {
    if (!admin) return;
    let live = true;
    setProfErr(null);
    listConnectorCredentials(connector.id).then(
      (p) => live && setProfiles(p),
      (e) => live && setProfErr(errorText(e, "Saved connections didn’t load.")),
    );
    return () => {
      live = false;
    };
  }, [admin, connector.id, reload]);

  React.useEffect(() => {
    if (profiles) onSaved(profiles.filter((p) => !p.revoked_at).length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profiles]);

  const save = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy) return;
    const form = e.currentTarget;
    const v = new FormData(form);
    const text = (n: string) => String(v.get(n) ?? "").trim();
    setBusy("save");
    setFormErr(null);
    try {
      const p = await saveConnectorCredential({
        connector_id: connector.id,
        label: text("label"),
        base_url: text("base_url"),
        auth_type: auth,
        secret: Object.fromEntries(AUTH_FIELDS[auth].map(({ name }) => [name, text(name)]).filter(([, x]) => x !== "")),
      });
      setProfiles((rows) => [p, ...(rows ?? [])]);
      form.reset();
      setAuth("bearer");
      toast("Connection saved. Test it to check access.");
    } catch (x) {
      setFormErr(errorText(x, "The connection wasn’t saved."));
    } finally {
      setBusy("");
    }
  };

  const test = async (p: ConnectorCredentialProfile) => {
    if (busy) return;
    setBusy(`test:${p.id}`);
    setProbes((s) => {
      const n = { ...s };
      delete n[p.id];
      return n;
    });
    try {
      const r = await probeConnectorCredential(p.id);
      setProbes((s) => ({ ...s, [p.id]: r }));
    } catch (x) {
      setProbes((s) => ({ ...s, [p.id]: { error: errorText(x, "The test didn’t run.") } }));
    } finally {
      setBusy("");
    }
  };

  const revoke = async (p: ConnectorCredentialProfile) => {
    setBusy(`revoke:${p.id}`);
    try {
      const r = await revokeConnectorCredential(p.id);
      setProfiles((rows) => (rows ?? []).map((x) => (x.id === r.id ? r : x)));
      setConfirm(null);
      toast("Connection revoked.");
    } catch (x) {
      toast(errorText(x, "The connection wasn’t revoked."));
    } finally {
      setBusy("");
    }
  };

  const apis = (connector.api_version ?? "").split("/").map((s) => s.trim()).filter(Boolean);
  const bomLabel = sap ? "Preview a BOM" : "Read an assembly";

  return (
    <Sheet label="Connector">
      <div className="top">
        <h2 className="stitle">{shortLabel(connector)}</h2>
        <p className="smeta">{sap ? "Live · read only · BOM preview only" : "Live · read only · BOM preview and import"}</p>
      </div>
      <div className="scroll">
        <div className="swap">
          <div className="gh">
            <span>Reads</span>
            <span>Read only</span>
          </div>
          <div className="apis">
            {connector.api_name ? <span>{connector.api_name}</span> : null}
            {apis.map((a) => (
              <span key={a}>{a}</span>
            ))}
          </div>
          {admin === false ? (
            <p style={{ margin: "0 12px 8px", color: "var(--ink2)", fontSize: 13 }}>An organization admin can save, test and use a connection here.</p>
          ) : admin === null ? (
            <p role="status" style={{ margin: "0 12px 8px", color: "var(--ink3)", fontSize: 13 }}>
              Checking your role…
            </p>
          ) : (
            <>
              <div className="gh">
                <span>Saved connections</span>
                <span className="num">{profiles?.length ?? ""}</span>
              </div>
              {profErr ? (
                <p style={{ margin: "0 12px 6px", color: "var(--bad)", fontSize: 13, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }} role="alert">
                  Saved connections didn’t load.
                  <button className="btn sm" type="button" onClick={() => setReload((n) => n + 1)}>
                    Retry
                  </button>
                </p>
              ) : !profiles ? (
                <p role="status" style={{ margin: "0 12px 6px", color: "var(--ink3)", fontSize: 13 }}>
                  Loading saved connections…
                </p>
              ) : profiles.length === 0 ? (
                <p style={{ margin: "0 12px 6px", color: "var(--ink2)", fontSize: 13 }}>None yet. Save one below, then test it.</p>
              ) : (
                profiles.map((p) => {
                  const probe = probes[p.id];
                  return (
                    <div className="prof" key={p.id} aria-label={p.label} role="group">
                      <span>
                        <b>{p.label}</b> · <span className="url">{p.base_url}</span>
                      </span>
                      <span>{p.revoked_at ? `Revoked ${whenLabel(p.revoked_at)}` : "Credential saved"}</span>
                      {!p.revoked_at && confirm !== p.id ? (
                        <div className="acts">
                          <button className="btn sm" type="button" onClick={() => void test(p)} disabled={!!busy}>
                            {busy === `test:${p.id}` ? "Testing…" : "Test connection"}
                          </button>
                          <Link className="btn sm" href={`${R.bom}?profile=${encodeURIComponent(p.id)}`}>
                            {bomLabel}
                          </Link>
                          <button className="btn sm" type="button" onClick={() => setConfirm(p.id)} disabled={!!busy}>
                            Revoke
                          </button>
                        </div>
                      ) : null}
                      {probe ? (
                        "error" in probe ? (
                          <span className="res bad" role="alert">
                            {probe.error}
                          </span>
                        ) : probe.connected ? (
                          <span className="res" role="status">
                            Product read succeeded ({probe.records_read} {probe.records_read === 1 ? "record" : "records"} checked). This test doesn’t check an assembly.
                          </span>
                        ) : (
                          <span className="res bad" role="alert">
                            Connection failed: {probe.reason ?? "no reason given"}
                          </span>
                        )
                      ) : null}
                      {confirm === p.id ? (
                        <div className="confirm" role="alertdialog" aria-label="Revoke connection">
                          <b>Revoke this connection?</b>
                          <span>Its stored credential is deleted. It stays listed as revoked. This can’t be undone.</span>
                          <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            <button className="btn danger sm" type="button" onClick={() => void revoke(p)} disabled={busy === `revoke:${p.id}`}>
                              {busy === `revoke:${p.id}` ? "Revoking…" : "Revoke connection"}
                            </button>
                            <button className="btn sm" type="button" onClick={() => setConfirm(null)} autoFocus>
                              Keep it
                            </button>
                          </span>
                        </div>
                      ) : null}
                    </div>
                  );
                })
              )}
              <div className="gh" style={{ marginTop: 4 }}>
                <span>New connection</span>
                <span>Admins only</span>
              </div>
              <form onSubmit={(e) => void save(e)}>
                <fieldset disabled={!!busy} style={{ border: 0, margin: 0, padding: 0, minWidth: 0 }}>
                  <legend className="sr">New connection</legend>
                  <div className="frm">
                    <label className="field">
                      Connection name
                      <input name="label" type="text" required maxLength={120} placeholder={`${sap ? "SAP" : "Windchill"} production`} autoComplete="off" />
                    </label>
                    <label className="field">
                      Service URL
                      <input name="base_url" type="url" required maxLength={500} placeholder={urlPh} autoComplete="off" />
                      <span className="fh">{sap ? "Your SAP host or API_PRODUCT_SRV service root." : "Your Windchill host or ProdMgmt service root."} Public HTTPS.</span>
                    </label>
                    <label className="field">
                      Authentication
                      <select value={auth} onChange={(e) => setAuth(e.target.value as ConnectorAuthType)}>
                        <option value="bearer">Bearer token</option>
                        <option value="basic">Username and password</option>
                        <option value="oauth2_client_credentials">OAuth client credentials</option>
                        <option value="api_key">API key header</option>
                      </select>
                    </label>
                    {AUTH_FIELDS[auth].map((f) => (
                      <label className="field" key={`${auth}:${f.name}`}>
                        {f.label}
                        <input
                          name={f.name}
                          type={f.type ?? "text"}
                          required={!f.optional}
                          maxLength={8192}
                          defaultValue={f.defaultValue}
                          autoComplete={f.type === "password" ? "new-password" : "off"}
                        />
                      </label>
                    ))}
                    {auth === "oauth2_client_credentials" ? <span className="fh">Uses client_secret_basic at the token endpoint.</span> : null}
                    <span className="fh">Credentials are encrypted on the server and never returned. Use an account limited to read access.</span>
                  </div>
                  {formErr ? (
                    <p className="fe" role="alert" style={{ margin: "8px 12px 0" }}>
                      {formErr}
                    </p>
                  ) : null}
                  <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap" }}>
                    <button className="btn ink" type="submit">
                      {busy === "save" ? "Saving…" : "Save connection"}
                    </button>
                  </div>
                </fieldset>
              </form>
            </>
          )}
          <div className="gh">
            <span>Limits</span>
            <span />
          </div>
          <p style={{ margin: "0 12px 8px", color: "var(--ink2)", fontSize: 13.5 }}>{connector.description}</p>
        </div>
        <p style={{ margin: "8px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
          {connector.raw_payload_stored ? "Raw responses are kept with the run." : "Raw responses aren’t stored after a read."}
        </p>
      </div>
    </Sheet>
  );
}
