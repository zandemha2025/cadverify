"use client";

/**
 * BOM preview (board M6): read a BOM through a saved read-only connection.
 * SAP S/4HANA previews a BOM explosion (no import); Windchill previews a
 * complete part structure, then imports exactly that preview after a confirm.
 * Any edit to the form clears the last preview, so an import always matches
 * what was read. Without a saved connection this is the way to set one up.
 */
import * as React from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api-base";
import { listConnectorCredentials, runConnectorBom, type ConnectorBomRun, type ConnectorCredentialProfile } from "@/lib/integrations-api";
import { R, TABS } from "../routes";
import { Content, Empty, Loading, Panel, Sheet, cx } from "../ui";
import { ManyWorld, PilotGate, errorText, useManyTabs, usePilotAccess, useToast } from "./common";
import { IMPORTS_GATE } from "./imports-screen";

const SAP_ID = "sap_s4hana_product_bom_readonly";
const WC_ID = "windchill_part_bom_readonly";
const isSap = (id: string) => id.startsWith("sap_");

async function getProfile(id: string): Promise<ConnectorCredentialProfile> {
  const res = await fetch(`${API_BASE}/integrations/credential-profiles/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (!res.ok) {
    const b = (await res.json().catch(() => null)) as { detail?: { message?: string } | string } | null;
    const msg = typeof b?.detail === "string" ? b.detail : b?.detail?.message;
    throw Object.assign(new Error(msg || `The connection didn’t load (${res.status}).`), { status: res.status });
  }
  return ((await res.json()) as { profile: ConnectorCredentialProfile }).profile;
}

export function BomScreen({ profileId }: { profileId: string | null }) {
  const [access] = usePilotAccess();
  const tabs = useManyTabs();
  const [toastNode, toast] = useToast();
  const [profile, setProfile] = React.useState<ConnectorCredentialProfile | null>(null);
  const [profErr, setProfErr] = React.useState<{ msg: string; status?: number } | null>(null);
  const [others, setOthers] = React.useState<ConnectorCredentialProfile[] | null>(null);
  const [pid, setPid] = React.useState(profileId);
  const [run, setRun] = React.useState<ConnectorBomRun | null>(null);
  const [runErr, setRunErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<"" | "read" | "import">("");
  const [asking, setAsking] = React.useState(false);
  const formRef = React.useRef<HTMLFormElement>(null);

  React.useEffect(() => setPid(profileId), [profileId]);

  React.useEffect(() => {
    Promise.all([listConnectorCredentials(SAP_ID).catch(() => []), listConnectorCredentials(WC_ID).catch(() => [])]).then(([a, b]) =>
      setOthers([...a, ...b].filter((p) => !p.revoked_at)),
    );
  }, []);

  React.useEffect(() => {
    if (!pid) return;
    let live = true;
    setProfile(null);
    setProfErr(null);
    setRun(null);
    setRunErr(null);
    getProfile(pid).then(
      (p) => live && setProfile(p),
      (e) => live && setProfErr({ msg: errorText(e, "The connection didn’t load."), status: (e as { status?: number }).status }),
    );
    return () => {
      live = false;
    };
  }, [pid]);

  if (access === "gated") return <PilotGate {...IMPORTS_GATE} title="BOM preview" />;

  const sap = profile ? isSap(profile.connector_id) : true;
  const sysName = sap ? "SAP S/4HANA" : "PTC Windchill";
  const sysShort = sap ? "SAP" : "Windchill";
  const revoked = !!profile?.revoked_at;
  const passed = !!run && run.status === "passed" && run.mode === "dry_run";
  const otherSys = (others ?? []).find((p) => (sap ? !isSap(p.connector_id) : isSap(p.connector_id)));

  const clear = () => {
    if (run || runErr) {
      setRun(null);
      setRunErr(null);
      setAsking(false);
    }
  };

  const submit = async (mode: "dry_run" | "import") => {
    if (!profile || busy || revoked || !formRef.current) return;
    const form = formRef.current;
    if (!form.reportValidity()) return;
    const v = new FormData(form);
    const text = (n: string) => String(v.get(n) ?? "").trim();
    setBusy(mode === "import" ? "import" : "read");
    setRunErr(null);
    setAsking(false);
    try {
      const r = await runConnectorBom(profile.id, {
        part_id: text("part_id"),
        assembly_key: text("assembly_key"),
        mode,
        navigation_id: text("navigation_id") || undefined,
        sap_selection: sap
          ? {
              bill_of_material: text("bill_of_material"),
              variant: text("variant"),
              version: text("version"),
              engineering_change_document: text("engineering_change_document"),
              plant: text("plant"),
              application: text("application"),
              explosion_date: text("explosion_date"),
              explosion_level: Number(text("explosion_level")),
            }
          : undefined,
        expected_sha256: mode === "import" ? run?.file_sha256 : undefined,
      });
      setRun(r);
      if (mode === "import" && r.status === "passed") toast("Assembly replaced with the previewed BOM.");
    } catch (e) {
      setRun(null);
      setRunErr(errorText(e, "The BOM couldn’t be read. Try again."));
    } finally {
      setBusy("");
    }
  };

  const edges = run?.metadata?.preview_edges ?? [];
  const comps = run?.metadata?.preview_components ?? [];
  const runText = !run
    ? ""
    : run.status === "failed"
      ? run.errors.map((e) => e.reason).join(" ") || "The read failed."
      : sap
        ? `SAP read succeeded: ${run.rows_valid} component records. Assembly and quantities still unverified; nothing changed.`
        : run.mode === "import"
          ? `Imported ${run.imported_count} relationships into ${String(run.metadata.assembly_key ?? "")}.`
          : `Preview passed: ${run.rows_valid} relationships. Nothing changed.`;

  const nav = (
    <nav className="subnav" aria-label="Many parts">
      {tabs.map((t) => {
        const on = t.href === TABS.many[2].href;
        return (
          <Link key={t.href} href={t.href} className={cx(on && "on")} aria-current={on ? "page" : undefined}>
            {t.label}
            {"count" in t && t.count != null ? <b className="num">{t.count}</b> : null}
          </Link>
        );
      })}
    </nav>
  );

  // No connection chosen (or it can't be read): set one up or pick a saved one.
  if (!pid || profErr) {
    return (
      <ManyWorld label="BOM preview">
        <div className="pagehead">
          <h1 className="ptitle">BOM preview</h1>
          <p className="pmeta" style={{ marginTop: 6 }}>
            <span>SAP S/4HANA or PTC Windchill</span>
            <span>Read only</span>
          </p>
          {nav}
        </div>
        <Content>
          <Panel title={profErr ? "This connection isn’t available" : "Choose a saved connection"}>
            {profErr ? (
              <Empty title={profErr.status === 403 ? "Organization admins only" : "Connection not found"}>
                {profErr.status === 403 ? "An organization admin can read BOMs through a saved connection." : profErr.msg}
              </Empty>
            ) : null}
            {others === null ? (
              <Loading rows={2} label="Loading saved connections" />
            ) : others.length ? (
              <div className="list" role="list" aria-label="Saved connections">
                {others.map((p) => (
                  <div role="listitem" key={p.id}>
                    <Link className="lrow" href={`${R.bom}?profile=${encodeURIComponent(p.id)}`} onClick={() => setPid(p.id)}>
                      <span className={cx("ico live")} aria-hidden="true">
                        Live
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <b>{p.label}</b>
                        <small>
                          {isSap(p.connector_id) ? "SAP S/4HANA" : "PTC Windchill"} · {p.base_url}
                        </small>
                      </span>
                      <span />
                      <span className="c" style={{ fontWeight: 500, color: "var(--ink3)", fontSize: 12.5 }}>
                        {isSap(p.connector_id) ? "Preview a BOM" : "Read an assembly"}
                      </span>
                    </Link>
                  </div>
                ))}
              </div>
            ) : (
              <Empty title="No saved connection" actions={<Link className="btn sm ink" href={R.imports}>Set one up in Imports</Link>}>
                A BOM is read through a saved read-only SAP S/4HANA or Windchill connection. An organization admin saves and tests it in Imports.
              </Empty>
            )}
          </Panel>
        </Content>
        <Sheet label="BOM read" style={{ bottom: "auto" }}>
          <div className="top">
            <h2 className="stitle">BOM preview</h2>
            <p className="smeta">Read only · nothing in SAP or Windchill changes</p>
          </div>
          <div className="scroll">
            <div className="kv">
              <span>SAP S/4HANA</span>
              <b>Preview a BOM explosion</b>
              <span>PTC Windchill</span>
              <b>Preview, then import</b>
            </div>
            <div style={{ padding: "8px 12px 12px" }}>
              <Link className="btn sm" href={R.imports}>
                Back to Imports
              </Link>
            </div>
          </div>
        </Sheet>
        {toastNode}
      </ManyWorld>
    );
  }

  return (
    <ManyWorld label="BOM preview">
      <div className="pagehead">
        <h1 className="ptitle">BOM preview</h1>
        <p className="pmeta" style={{ marginTop: 6 }}>
          <span>{sysName}</span>
          <span>{profile?.label ?? "Loading"}</span>
          <span>Read only</span>
          <span>{sap ? "Preview only" : "Preview, then import"}</span>
        </p>
        {nav}
      </div>
      <Content>
        <Panel title="Relationships" note={run && edges.length ? (run.metadata.preview_truncated ? `First 20 of ${run.rows_valid}` : `${edges.length} shown`) : "From the preview"}>
          <div aria-live="polite">
            {run ? (
              <p className={run.status === "failed" ? "bad2" : "ok2"} role={run.status === "failed" ? "alert" : "status"}>
                {runText}
              </p>
            ) : null}
            {runErr ? (
              <p className="bad2" role="alert">
                {runErr}
              </p>
            ) : null}
          </div>
          {edges.length ? (
            <div className="tscroll">
              <table className="bt data">
                <thead>
                  <tr>
                    <th scope="col">Parent ID</th>
                    <th scope="col">Child ID and name</th>
                    <th scope="col" className="r">
                      Count
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {edges.map((e) => (
                    <tr key={`${e.parent_ref}:${e.child_ref}`}>
                      <td>{e.parent_ref}</td>
                      <td>
                        {e.child_ref} · {e.child_name}
                      </td>
                      <td className="r">{e.qty_per_parent}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : !profile ? (
            <Loading rows={2} label="Loading the connection" />
          ) : (
            <Empty
              title={run ? "No relationships in this read" : "No preview yet"}
              actions={
                !run ? (
                  <button className="btn sm ink" type="button" onClick={() => void submit("dry_run")} aria-disabled={!!busy || revoked}>
                    {busy === "read" ? "Reading…" : "Preview BOM"}
                  </button>
                ) : undefined
              }
            >
              {revoked ? "This connection is revoked. Save a new one in Imports." : "Preview reads the BOM and saves nothing."}
            </Empty>
          )}
        </Panel>
        {sap ? (
          <Panel title="Components" note="SAP units, not converted">
            {comps.length ? (
              <div className="tscroll">
                <table className="bt data">
                  <thead>
                    <tr>
                      <th scope="col">Level · header</th>
                      <th scope="col">Component · item</th>
                      <th scope="col" className="r">
                        Item qty
                      </th>
                      <th scope="col" className="r">
                        Header base
                      </th>
                      <th scope="col" className="r">
                        Exploded qty
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {comps.map((c, i) => (
                      <tr key={i}>
                        <td>
                          {c.level} · {c.header_material}
                        </td>
                        <td>
                          {c.component} · {c.item_number}
                        </td>
                        <td className="r">
                          {c.item_quantity} {c.item_unit}
                        </td>
                        <td className="r">
                          {c.header_quantity} {c.header_unit}
                        </td>
                        <td className="r">{c.exploded_quantity}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p style={{ margin: 0, padding: "0 16px 6px", color: "var(--ink3)", fontSize: 13 }}>{run ? "No component records in this read." : "Shown after a preview."}</p>
            )}
            <p style={{ margin: 0, padding: "8px 16px 14px", color: "var(--ink3)", fontSize: 12.5 }}>
              Confirm exploded quantity units in SAP before using them.{run?.metadata?.preview_truncated ? " First 20 records shown." : ""}
            </p>
          </Panel>
        ) : null}
      </Content>

      <Sheet label="BOM read">
        <div className="top">
          <h2 className="stitle">{sap ? "Preview a SAP BOM explosion" : "Read or import an assembly"}</h2>
          <p className="smeta">{profile ? `${profile.label} · read only` : "Loading"}</p>
          <div style={{ marginTop: 12 }}>
            <span className="seg" role="group" aria-label="System">
              {(["sap", "wc"] as const).map((k) => {
                const on = (k === "sap") === sap;
                const target = on ? null : otherSys;
                return (
                  <button
                    key={k}
                    type="button"
                    className={cx(on && "on")}
                    aria-pressed={on}
                    aria-disabled={!on && !target}
                    title={!on && !target ? `No saved ${k === "sap" ? "SAP" : "Windchill"} connection` : undefined}
                    onClick={() => {
                      if (target) {
                        setPid(target.id);
                        window.history.replaceState(null, "", `${R.bom}?profile=${encodeURIComponent(target.id)}`);
                      }
                    }}
                  >
                    {k === "sap" ? "SAP S/4HANA" : "Windchill"}
                  </button>
                );
              })}
            </span>
          </div>
        </div>
        <div className="scroll">
          <p style={{ margin: "6px 12px 8px", color: "var(--ink2)", fontSize: 13 }}>
            {sap
              ? "Reads a material BOM at a date and depth, for a required quantity of 1. A read doesn’t verify a complete assembly or quantities. SAP assemblies can’t be imported. SAP isn’t changed."
              : "Previews a complete part structure, then imports whole-part counts. Windchill isn’t changed."}
          </p>
          <form
            ref={formRef}
            key={profile?.id ?? "none"}
            onChange={clear}
            onSubmit={(e) => {
              e.preventDefault();
              void submit("dry_run");
            }}
          >
            <fieldset disabled={!!busy || revoked || !profile} style={{ border: 0, margin: 0, padding: 0, minWidth: 0 }}>
              <legend className="sr">{sap ? "SAP BOM selection" : "Windchill assembly"}</legend>
              {sap ? (
                <div className="frm2">
                  <label className="field">
                    Root material
                    <input name="part_id" type="text" required maxLength={40} placeholder="EX_H" />
                  </label>
                  <label className="field">
                    Preview name
                    <input name="assembly_key" type="text" required maxLength={120} placeholder="Vehicle assembly" />
                  </label>
                  <label className="field">
                    BOM number
                    <input name="bill_of_material" type="text" required maxLength={8} placeholder="00058298" />
                  </label>
                  <label className="field">
                    Alternative
                    <input name="variant" type="text" required maxLength={2} placeholder="1" />
                  </label>
                  <label className="field">
                    Plant
                    <input name="plant" type="text" required maxLength={4} placeholder="0001" />
                  </label>
                  <label className="field">
                    Explosion application
                    <input name="application" type="text" required maxLength={4} placeholder="PP01" />
                  </label>
                  <label className="field">
                    Effective date
                    <input name="explosion_date" type="date" required />
                  </label>
                  <label className="field">
                    Preview depth
                    <input name="explosion_level" type="number" min={1} max={99} step={1} defaultValue={1} required />
                  </label>
                  <label className="field">
                    BOM version <span className="fh">Optional</span>
                    <input name="version" type="text" maxLength={4} />
                  </label>
                  <label className="field">
                    Change document <span className="fh">Optional</span>
                    <input name="engineering_change_document" type="text" maxLength={12} />
                  </label>
                  <span className="fh full">
                    Reads SAP BOM API v2. Paginated, malformed, empty, mismatched-root and over-1 MB responses are rejected. Up to 9,998 records. Quantities keep their SAP units.
                  </span>
                </div>
              ) : (
                <div className="frm2">
                  <label className="field full">
                    Root part iteration ID
                    <input name="part_id" type="text" required maxLength={120} placeholder="OR:wt.part.WTPart:12345" />
                  </label>
                  <label className="field full">
                    Saved assembly name
                    <input name="assembly_key" type="text" required maxLength={120} placeholder="Vehicle assembly" />
                    <span className="fh">Import replaces the assembly saved under this name.</span>
                  </label>
                  <label className="field full">
                    Saved navigation criteria ID <span className="fh">Optional</span>
                    <input name="navigation_id" type="text" maxLength={120} placeholder="OR:wt.filter.NavigationCriteria:12345" />
                  </label>
                  <span className="fh full">
                    Without a saved filter, Windchill applies its default navigation criteria. Missing permissions, unresolved parts, fractional counts, other units and over-1 MB responses are rejected.
                  </span>
                </div>
              )}
              <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap", alignItems: "center" }}>
                <button className="btn ink" type="submit">
                  {busy === "read" ? "Reading…" : "Preview BOM"}
                </button>
                {!sap ? (
                  <button
                    className="btn"
                    type="button"
                    aria-disabled={!passed || !!busy}
                    onClick={() => {
                      if (passed && !busy) setAsking(true);
                    }}
                  >
                    {busy === "import" ? "Importing…" : "Import previewed BOM"}
                  </button>
                ) : null}
              </div>
            </fieldset>
          </form>
          {!sap ? (
            <p style={{ margin: "0 12px", color: "var(--ink3)", fontSize: 12.5 }}>{passed ? "Imports exactly this preview." : "Preview first. Import uses that exact result."}</p>
          ) : null}
          {asking && passed ? (
            <div className="confirm" role="alertdialog" aria-label="Replace saved assembly" style={{ margin: "8px 12px 0" }}>
              <b>Replace the saved assembly?</b>
              <span>The exact BOM you previewed replaces the one saved under this name. Windchill isn’t changed.</span>
              <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="btn danger sm" type="button" onClick={() => void submit("import")} autoFocus>
                  Replace assembly
                </button>
                <button className="btn sm" type="button" onClick={() => setAsking(false)}>
                  Cancel
                </button>
              </span>
            </div>
          ) : null}
          <div className="gh">
            <span>Connection</span>
            <span />
          </div>
          <div className="kv">
            <span>Connection</span>
            <b>{profile?.label ?? "—"}</b>
            <span>Status</span>
            <b>{profile ? (revoked ? "Revoked" : "Credential saved") : "—"}</b>
            <span>Changes in {sysShort}</span>
            <b>None, read only</b>
          </div>
          <div style={{ padding: "8px 12px" }}>
            <Link className="btn sm" href={R.imports}>
              Back to Imports
            </Link>
          </div>
        </div>
      </Sheet>
      {toastNode}
    </ManyWorld>
  );
}
