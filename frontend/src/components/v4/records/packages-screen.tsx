"use client";

/**
 * Supplier packages (board P5): build a package from saved records (title,
 * supplier, a note to the supplier, original CAD where it was kept), see what
 * goes in the ZIP and what the brief warns about, list the packages and
 * download them. A package is a download: ScaleCAD doesn't send it and doesn't
 * track replies. /app/parts/packages/{id} opens one package in the sheet.
 */
import * as React from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import type { RfqPackageDetail, RfqPackageSummary } from "@/lib/api";
import { useAuth } from "@/components/ui/auth-provider";
import { canMutateWorkspace } from "@/lib/role-capabilities";
import { R, TABS } from "../routes";
import { Chip, Content, PageHead, cx } from "../ui";
import { ApiError, buildPackage, downloadPackage, errorText, getPackage, listPackages, usePortfolio, useRecordList } from "./api";
import { FileIcon, Glyph, LoadFailed, NoneYet, NotFound, RecSheet, RecWorld, Skeleton, useToast } from "./common";
import { groupByPart, summaryLines } from "./facts";
import { money, num, plural, short, stampUtc, wayLower } from "./words";

/* the selection survives opening a record and coming back ("Open keeps your selection") */
let keptPicks: Set<string> = new Set();
let keptScope: "latest" | "all" = "latest";

const PACKAGE_NOTE = "ScaleCAD doesn't send packages or track replies. Download the ZIP and send it to your supplier yourself.";

export function PackagesScreen() {
  const params = useParams<{ id?: string }>();
  const pkgId = typeof params?.id === "string" ? decodeURIComponent(params.id) : null;
  const sp = useSearchParams();
  const router = useRouter();
  const { user } = useAuth();
  const canEdit = canMutateWorkspace(user?.role);
  const list = useRecordList();
  const pf = usePortfolio();
  const [toastNode, toast] = useToast();

  const [pkgs, setPkgs] = React.useState<RfqPackageSummary[] | null>(null);
  const [pkgErr, setPkgErr] = React.useState<string | null>(null);
  const loadPkgs = React.useCallback(async () => {
    setPkgErr(null);
    try {
      setPkgs(await listPackages());
    } catch (e) {
      setPkgErr(errorText(e, "Packages didn't load."));
    }
  }, []);
  React.useEffect(() => {
    void loadPkgs();
  }, [loadPkgs]);

  const [picked, setPicked] = React.useState<Set<string>>(() => {
    const p = new Set(keptPicks);
    const fromUrl = sp?.get("pick");
    if (fromUrl) p.add(fromUrl);
    return p;
  });
  React.useEffect(() => {
    keptPicks = picked;
  }, [picked]);
  const [scope, setScope] = React.useState<"latest" | "all">(keptScope);
  React.useEffect(() => {
    keptScope = scope;
  }, [scope]);
  const [q, setQ] = React.useState("");

  const rows = list.rows;
  const latest = React.useMemo(() => groupByPart(rows ?? []).map((g) => g.rows[0]), [rows]);
  // "Latest per part" also keeps any record you picked, so a selection never hides.
  const inScope = scope === "all" ? rows ?? [] : (rows ?? []).filter((r) => latest.includes(r) || picked.has(r.id));
  const needle = q.trim().toLowerCase();
  const shown = inScope.filter((r) => !needle || r.filename.toLowerCase().includes(needle) || r.id.toLowerCase().includes(needle.replace(/^#/, "")));
  const allOn = shown.length > 0 && shown.every((r) => picked.has(r.id));
  const chosen = (rows ?? []).filter((r) => picked.has(r.id));
  const missing = [...picked].filter((id) => !(rows ?? []).some((r) => r.id === id));
  const n = picked.size;
  const nApproved = chosen.filter((r) => r.approval_status === "approved").length;
  const nStale = chosen.filter((r) => r.is_stale).length;
  const parts = new Set(chosen.map((r) => r.mesh_hash || r.filename)).size;
  const priceOf = React.useMemo(() => {
    const m = new Map<string, string>();
    for (const r of pf.data?.rows ?? []) {
      const id = (r as { cost_decision?: { id?: string } }).cost_decision?.id;
      if (id && r.unit_cost && r.unit_cost.usd != null) m.set(id, `${money(r.unit_cost.usd)}${r.unit_cost.qty != null && r.unit_cost.qty !== 10 ? ` at ${num(r.unit_cost.qty)}` : ""}`);
      else if (id && r.unit_cost?.withheld) m.set(id, "Withheld");
    }
    return m;
  }, [pf.data]);
  const hasCtx = chosen.some((r) => pf.data?.rows.find((x) => x.part_key === r.mesh_hash)?.context?.service_environment);

  const toggle = (id: string) =>
    setPicked((p) => {
      const nx = new Set(p);
      if (nx.has(id)) nx.delete(id);
      else nx.add(id);
      return nx;
    });
  const selectShown = () =>
    setPicked((p) => {
      const nx = new Set(p);
      for (const r of shown) {
        if (allOn) nx.delete(r.id);
        else nx.add(r.id);
      }
      return nx;
    });

  const tabs = TABS.parts;
  const nPk = pkgs?.length ?? 0;

  return (
    <RecWorld label="Supplier packages">
      <PageHead
        title="Supplier packages"
        meta={[
          pkgs ? (
            <>
              <b className="num">{nPk}</b> {nPk === 1 ? "package" : "packages"}
            </>
          ) : pkgErr ? (
            "Packages didn't load"
          ) : (
            "Loading packages"
          ),
          ...(rows
            ? [
                <>
                  <b className="num">
                    {rows.length}
                    {list.more ? "+" : ""}
                  </b>{" "}
                  records available
                </>,
                <>
                  <b className="num">{rows.filter((r) => r.approval_status === "approved").length}</b> approved
                </>,
              ]
            : []),
        ]}
        tabs={tabs}
        tabsLabel="Parts"
      />
      <Content>
        <section className="panel" aria-label="Packages">
          {pkgs === null ? (
            pkgErr ? (
              <LoadFailed what="packages" detail={pkgErr} onRetry={() => void loadPkgs()} />
            ) : (
              <Skeleton rows={2} label="Loading packages" />
            )
          ) : pkgs.length === 0 ? (
            <div className="empty" style={{ padding: "22px 24px" }}>
              <b>No supplier packages</b>
              <span>A package is built from one or more records.</span>
            </div>
          ) : (
            <>
              <div className="ph">
                <h2>Packages</h2>
                <span className="num">{nPk}</span>
              </div>
              <div className="list">
                {pkgs.map((p) => (
                  <PackageRow key={p.id} p={p} on={p.id === pkgId} toast={toast} onOpen={() => router.push(R.pkg(p.id), { scroll: false })} />
                ))}
              </div>
            </>
          )}
        </section>

        <section className="panel" id="records" aria-label="Records to include">
          <div className="ph">
            <h2>Records</h2>
            <span className="num">{n} selected</span>
          </div>
          {!rows ? (
            list.error ? (
              <LoadFailed what="records" detail={list.error} onRetry={() => void list.reload()} />
            ) : (
              <Skeleton rows={4} label="Loading records" />
            )
          ) : rows.length === 0 ? (
            <NoneYet
              title="No records"
              actions={
                <Link className="btn sm ink" href={R.check}>
                  Check a part
                </Link>
              }
            >
              One is saved each time you check a part.
            </NoneYet>
          ) : (
            <>
              <div className="tools">
                <input type="search" aria-label="Find records by file name" placeholder="Find records" value={q} onChange={(e) => setQ(e.target.value)} />
                <span className="seg" role="group" aria-label="Which records">
                  {(
                    [
                      ["latest", "Latest per part", latest.length],
                      ["all", "All records", rows.length],
                    ] as const
                  ).map(([k, label, c]) => (
                    <button key={k} type="button" className={cx(scope === k && "on")} aria-pressed={scope === k} onClick={() => setScope(k)}>
                      {label}{" "}
                      <span className="num" style={{ opacity: 0.7 }}>
                        {c}
                        {list.more ? "+" : ""}
                      </span>
                    </button>
                  ))}
                </span>
                <button type="button" className="btn sm" onClick={selectShown} disabled={!shown.length}>
                  {allOn ? "Clear shown" : "Select shown"}
                </button>
              </div>
              <div className="list">
                {shown.map((r) => {
                  const on = picked.has(r.id);
                  const l = summaryLines(r);
                  const flags = [r.approval_status === "approved" ? "approved" : "not approved", ...(r.is_stale ? ["out of date"] : [])];
                  return (
                    <div className={cx("pkrow", on && "on")} key={r.id}>
                      <button type="button" className="pkbtn" role="checkbox" aria-checked={on} aria-label={`Include ${r.filename}, ${l.what}, #${short(r.id)}`} onClick={() => toggle(r.id)}>
                        <span className="box" aria-hidden="true" />
                        <span className="th" aria-hidden="true">
                          <Glyph size={20} />
                        </span>
                        <span style={{ minWidth: 0 }}>
                          <b>{r.filename}</b>
                          <small>
                            {l.what} · {flags.join(" · ")} · #{short(r.id)}
                          </small>
                        </span>
                      </button>
                      <span className="c num">{priceOf.get(r.id) ?? ""}</span>
                      <Link href={R.record(r.id)}>Open</Link>
                    </div>
                  );
                })}
                {!shown.length ? (
                  <div className="empty" style={{ padding: 18 }}>
                    <b>No records match</b>
                    <span>Try another file name.</span>
                    <button type="button" className="btn sm" onClick={() => setQ("")}>
                      Clear search
                    </button>
                  </div>
                ) : null}
              </div>
              <div className="foot num">
                <span>
                  {shown.length} of {inScope.length}
                  {list.more ? "+" : ""} · Open keeps your selection
                </span>
                {list.more ? (
                  <button type="button" className="btn sm" onClick={() => void list.loadMore()} disabled={list.loadingMore}>
                    {list.loadingMore ? "Loading records…" : "Load older records"}
                  </button>
                ) : null}
              </div>
            </>
          )}
        </section>
      </Content>

      {pkgId ? (
        <PackageSheet key={pkgId} id={pkgId} toast={toast} />
      ) : (
        <Builder
          n={n}
          nApproved={nApproved}
          nStale={nStale}
          parts={parts}
          missing={missing.length}
          first={chosen[0] ?? null}
          hasCtx={hasCtx}
          canEdit={canEdit}
          onBuild={async (input) => {
            const pkg = await buildPackage({ ...input, ids: [...picked] });
            setPicked(new Set());
            toast("Package built");
            void loadPkgs();
            router.push(R.pkg(pkg.id), { scroll: false });
          }}
        />
      )}
      {toastNode}
    </RecWorld>
  );
}

function PackageRow({ p, on, onOpen, toast }: { p: RfqPackageSummary; on: boolean; onOpen: () => void; toast: (m: string) => void }) {
  const [busy, setBusy] = React.useState(false);
  return (
    <div className={cx("pkrow pgr", on && "on")}>
      <button type="button" className="pkbtn pgb" onClick={onOpen} aria-pressed={on}>
        <span className="th" aria-hidden="true">
          <FileIcon />
        </span>
        <span style={{ minWidth: 0 }}>
          <b>{p.title || "Supplier package"}</b>
          <small>
            {plural(p.item_count, "record")}
            {p.supplier_name ? ` · ${p.supplier_name}` : ""} · {stampUtc(p.created_at)}
          </small>
        </span>
      </button>
      <Chip tone="unk">Not sent</Chip>
      <button
        type="button"
        className="btn sm"
        disabled={busy}
        aria-label={`Download ${p.title || "package"} as a ZIP`}
        onClick={async () => {
          setBusy(true);
          try {
            toast(`Downloaded ${await downloadPackage(p.id, p.title)}`);
          } catch (e) {
            toast(errorText(e, "The ZIP didn't download."));
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Downloading" : "ZIP"}
      </button>
    </div>
  );
}

function Builder({
  n,
  nApproved,
  nStale,
  parts,
  missing,
  first,
  hasCtx,
  canEdit,
  onBuild,
}: {
  n: number;
  nApproved: number;
  nStale: number;
  parts: number;
  missing: number;
  first: { filename: string; id: string } | null;
  hasCtx: boolean;
  canEdit: boolean;
  onBuild: (i: { title: string; supplier: string; note: string; cad: boolean }) => Promise<void>;
}) {
  const auto = n === 1 && first ? `${first.filename} · quotes` : n ? `${parts > 1 ? `${parts} parts` : plural(n, "record")} · quotes` : "";
  const [title, setTitle] = React.useState<string | null>(null);
  const [supplier, setSupplier] = React.useState("");
  const [note, setNote] = React.useState("");
  const [cad, setCad] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const t = title ?? auto;
  const notApproved = n - nApproved;
  const off = !n || busy || !canEdit;

  return (
    <RecSheet label="The package">
      <div className="top">
        <h2 className="stitle">New package</h2>
        <p className="smeta">{n === 1 && first ? first.filename : n ? `${plural(n, "record")} from ${plural(parts, "part")}` : "No records selected"}</p>
        <div className="figs">
          <div className="fig">
            <span>Records</span>
            <b className="num">{n}</b>
            <small>selected</small>
          </div>
          <div className="fig">
            <span>Approved</span>
            <b className="num">{nApproved}</b>
            <small>of {n}</small>
          </div>
          <div className="fig">
            <span>Original CAD</span>
            <b className={cx("t", cad && "warn")}>{cad ? "Asked for" : "Not included"}</b>
            <small>Kept for batch uploads only</small>
          </div>
        </div>
      </div>
      <div className="scroll">
        <div className="pk-fields">
          <label className="field">
            Title
            <input type="text" value={t} maxLength={200} onChange={(e) => setTitle(e.target.value)} disabled={!canEdit} />
          </label>
          <label className="field">
            Supplier
            <input type="text" placeholder="Supplier name" value={supplier} maxLength={200} onChange={(e) => setSupplier(e.target.value)} disabled={!canEdit} />
          </label>
          <label className="field">
            Note to supplier
            <textarea placeholder="Tolerances, target date" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} disabled={!canEdit} />
          </label>
          <label className="chk">
            <input type="checkbox" checked={cad} onChange={(e) => setCad(e.target.checked)} disabled={!canEdit} />
            <span>
              Include original CAD where kept
              <small>Only parts checked in a batch ZIP keep their CAD. Single uploads aren&apos;t kept, so most records have none.</small>
            </span>
          </label>
        </div>
        <div className="gh">
          <span>Contents</span>
          <span>{n ? "one folder per record" : ""}</span>
        </div>
        <div className="files">
          {[
            ["Supplier brief", "supplier-brief.pdf"],
            ["Line items and sources", "line-items.csv"],
            ["Each record, full", "cost-decision.json"],
            ["Each record, cost inputs", "cost-drivers.csv"],
            ["Each record, should-cost report", "should-cost-report.pdf"],
            ...(hasCtx ? [["Service conditions declared on the part", "part-context.json"]] : []),
            ["Manifest", "package_manifest.json"],
          ].map(([k, f]) => (
            <div className="fl" key={f}>
              <FileIcon />
              <span>{k}</span>
              <b>{f}</b>
            </div>
          ))}
          <div className="fl no">
            <FileIcon dashed />
            <span>Original CAD file</span>
            <b>{cad ? "where kept" : "not included"}</b>
          </div>
        </div>
        <div className="gh">
          <span>Warnings in the brief</span>
          <span />
        </div>
        {notApproved > 0 ? (
          <div className="pk-warn">
            <i aria-hidden="true">!</i>
            <span>{plural(notApproved, "record")} not approved.</span>
          </div>
        ) : null}
        {nStale > 0 ? (
          <div className="pk-warn">
            <i aria-hidden="true">!</i>
            <span>{plural(nStale, "record")} out of date. Check the part again first.</span>
          </div>
        ) : null}
        {missing > 0 ? (
          <div className="pk-warn">
            <i aria-hidden="true">!</i>
            <span>{plural(missing, "selected record")} not in the loaded list; it&apos;s included by its id.</span>
          </div>
        ) : null}
        <div className="pk-warn">
          <i aria-hidden="true">!</i>
          <span>Should-cost evidence, not a quote.</span>
        </div>
        {err ? (
          <p className="err2" role="alert">
            {err}
          </p>
        ) : null}
        <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap", alignItems: "center" }}>
          <button
            className={cx("btn ink", off && "off")}
            type="button"
            aria-disabled={off}
            onClick={async () => {
              if (off) return;
              setBusy(true);
              setErr(null);
              try {
                await onBuild({ title: t, supplier, note, cad });
              } catch (e) {
                setErr(errorText(e, "The package wasn't built."));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Building…" : `Build package (${n})`}
          </button>
          <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Not sent by ScaleCAD.</span>
        </div>
        <p className="ro-note" style={{ margin: "0 12px 12px" }}>
          {canEdit ? PACKAGE_NOTE : "Read only. Analysts and admins build packages."}
        </p>
      </div>
    </RecSheet>
  );
}

function PackageSheet({ id, toast }: { id: string; toast: (m: string) => void }) {
  const [pkg, setPkg] = React.useState<RfqPackageDetail | null>(null);
  const [err, setErr] = React.useState<{ text: string; notFound: boolean } | null>(null);
  const [dl, setDl] = React.useState<"idle" | "busy" | "done">("idle");
  const load = React.useCallback(async () => {
    setErr(null);
    try {
      setPkg(await getPackage(id));
    } catch (e) {
      setErr({ text: errorText(e, "The package didn't load."), notFound: e instanceof ApiError && e.status === 404 });
    }
  }, [id]);
  React.useEffect(() => {
    void load();
  }, [load]);

  if (!pkg) {
    return (
      <RecSheet label="The package">
        {err ? (
          err.notFound ? (
            <NotFound title="Package not found" back={{ label: "Back to packages", href: R.packages }} onRetry={() => void load()}>
              It was never built, or the link is wrong.
            </NotFound>
          ) : (
            <LoadFailed what="the package" detail={err.text} onRetry={() => void load()} />
          )
        ) : (
          <Skeleton rows={5} label="Loading the package" />
        )}
      </RecSheet>
    );
  }
  const requested = (pkg.metadata as { raw_cad_requested?: boolean })?.raw_cad_requested === true;
  const cadKept = pkg.items.filter((i) => i.raw_cad?.included).length;
  return (
    <RecSheet label="The package">
      <div className="top">
        <h2 className="stitle" style={{ overflowWrap: "anywhere" }}>
          {pkg.title || "Supplier package"}
        </h2>
        <p className="smeta">Built {stampUtc(pkg.created_at)}</p>
        <div className="figs">
          <div className="fig">
            <span>Records</span>
            <b className="num">{pkg.item_count}</b>
            <small>in the ZIP</small>
          </div>
          <div className="fig">
            <span>Approved</span>
            <b className="num">{pkg.approved_count}</b>
            <small>of {pkg.item_count}</small>
          </div>
          <div className="fig">
            <span>Supplier</span>
            <b className="t">{pkg.supplier_name || "Not named"}</b>
            <small>Not sent by ScaleCAD</small>
          </div>
        </div>
      </div>
      <div className="scroll">
        <div style={{ display: "flex", gap: 8, padding: "10px 12px", flexWrap: "wrap" }}>
          <button
            className="btn ink sm"
            type="button"
            disabled={dl === "busy"}
            onClick={async () => {
              setDl("busy");
              try {
                toast(`Downloaded ${await downloadPackage(pkg.id, pkg.title)}`);
                setDl("done");
              } catch (e) {
                toast(errorText(e, "The ZIP didn't download."));
                setDl("idle");
              }
            }}
          >
            {dl === "busy" ? "Downloading" : dl === "done" ? "Downloaded" : "Download ZIP"}
          </button>
          <Link className="btn sm" href={R.packages}>
            New package
          </Link>
        </div>
        <p className="ro-note" style={{ margin: "0 12px" }}>
          {PACKAGE_NOTE}
        </p>
        <div className="gh">
          <span>Records in this package</span>
          <span className="num">{pkg.items.length}</span>
        </div>
        <div>
          {pkg.items.map((i) => (
            <Link key={i.decision.id} className="mr2" href={R.record(i.decision.id)}>
              <span style={{ minWidth: 0 }}>
                {i.decision.filename}
                <small style={{ display: "block" }}>
                  {i.decision.make_now_process ? `Cheapest: ${wayLower(i.decision.make_now_process)}` : "No way priced"} · {i.decision.approval_status === "approved" ? "approved" : "not approved"}
                  {i.decision.is_stale ? " · out of date" : ""} · #{short(i.decision.id)}
                </small>
              </span>
              <span className="o">Open</span>
            </Link>
          ))}
        </div>
        {pkg.warnings.length ? (
          <>
            <div className="gh">
              <span>Warnings in the brief</span>
              <span className="num">{pkg.warnings.length}</span>
            </div>
            {pkg.warnings.map((w, k) => (
              <div className="pk-warn" key={`${w.code}-${k}`}>
                <i aria-hidden="true">!</i>
                <span>{w.message}</span>
              </div>
            ))}
          </>
        ) : null}
        <div className="gh">
          <span>Contents</span>
          <span />
        </div>
        <div className="kv ev">
          <span>Brief</span>
          <b>supplier-brief.pdf and .md</b>
          <span>Per record</span>
          <b>cost-decision.json, cost-drivers.csv, should-cost-report.pdf</b>
          <span>Original CAD</span>
          <b>{pkg.raw_cad_included ? `Included for ${plural(cadKept, "record")}` : requested ? "Asked for; none of these records kept it" : "Not asked for"}</b>
        </div>
      </div>
    </RecSheet>
  );
}
