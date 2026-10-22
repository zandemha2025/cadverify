"use client";

/**
 * RFQ packages (board P5): build a request for quote from saved records, see
 * what goes in the ZIP, list the packages, download one or share it as a link.
 * ScaleCAD doesn't send a package and doesn't track replies.
 *
 * What a supplier receives, by default, is what a supplier quotes from: each
 * part's name, part number, material, quantity, specs, the buyer's note and
 * the CAD; who asks and the reply-by date. Our cost goes only when the buyer
 * turns "Include our cost estimate" on, with a warning; review state never
 * (backend src/services/rfq_package_service.py). /app/parts/packages/{id}
 * opens one package in the sheet.
 */
import * as React from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import type { CostDecisionSummary, RfqPackageDetail, RfqPackageSummary } from "@/lib/api";
import { useAuth } from "@/components/ui/auth-provider";
import { canMutateWorkspace } from "@/lib/role-capabilities";
import { R, TABS } from "../routes";
import { Chip, Content, PageHead, cx } from "../ui";
import { ShareDialog } from "../share/share-dialog";
import { COST_WARNING } from "../share/words";
import { linkEndText, type LinkStatus } from "../datacontrol/words";
import {
  ApiError,
  buildPackage,
  downloadPackage,
  errorText,
  getPackage,
  listPackages,
  previewPackage,
  sharePackage,
  unsharePackage,
  useRecordList,
  type PackagePreviewItem,
  type Requester,
} from "./api";
import { Confirm, FileIcon, Glyph, LoadFailed, NoneYet, NotFound, RecSheet, RecWorld, Skeleton, useToast } from "./common";
import { groupByPart } from "./facts";
import { QTY_FROM, pickerLine } from "./package-words";
import { num, plural, short, stampUtc } from "./words";
import "./packages.css";

/* the selection survives opening a record and coming back ("Open keeps your selection") */
let keptPicks: Set<string> = new Set();
let keptScope: "latest" | "all" = "latest";

const PACKAGE_NOTE = "ScaleCAD doesn't send packages or track replies. Download the ZIP or share a link, and send it yourself.";
/** What a supplier's copy leaves out (backend src/services/outbound.py and rfq_package_service.py). */
const PACKAGE_PRIVATE = "Never in it: your machines, rates, in-house routes and choices, approvals and notes.";

/* ── previews: each record as the package would ask for it ──────────────── */

const previewCache = new Map<string, PackagePreviewItem>();
let requesterCache: Requester | null = null;

/** Previews for these records (cached); `cad` also looks for the kept file. */
function usePreviews(ids: string[], cad: boolean): { byId: Map<string, PackagePreviewItem>; requester: Requester | null } {
  const key = ids.join(",");
  const [, bump] = React.useReducer((n: number) => n + 1, 0);
  React.useEffect(() => {
    const want = ids.filter((id) => {
      const have = previewCache.get(id);
      return !have || (cad && have.cad_kept == null);
    });
    if (!want.length && (requesterCache || !ids.length)) return;
    let live = true;
    (async () => {
      for (let i = 0; i < Math.max(want.length, 1); i += 100) {
        const chunk = want.slice(i, i + 100);
        try {
          const r = await previewPackage(chunk.length ? chunk : ids.slice(0, 1), cad);
          // A list read (cad: false) never forgets what a picked read learned about the kept file.
          for (const x of r.items) previewCache.set(x.id, { ...x, cad_kept: x.cad_kept ?? previewCache.get(x.id)?.cad_kept ?? null });
          if (r.requested_by) requesterCache = r.requested_by;
        } catch {
          /* the list still works without prices */
        }
      }
      if (live) bump();
    })();
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, cad]);
  const byId = new Map<string, PackagePreviewItem>();
  for (const id of ids) {
    const x = previewCache.get(id);
    if (x) byId.set(id, x);
  }
  return { byId, requester: requesterCache };
}

export function PackagesScreen() {
  const params = useParams<{ id?: string }>();
  const pkgId = typeof params?.id === "string" ? decodeURIComponent(params.id) : null;
  const sp = useSearchParams();
  const router = useRouter();
  const { user } = useAuth();
  const canEdit = canMutateWorkspace(user?.role);
  const list = useRecordList();
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
  const parts = new Set(chosen.map((r) => r.mesh_hash || r.filename)).size;

  // Prices at each record's quantity (buyer-11), and the picked records with their kept CAD.
  const shownIds = React.useMemo(() => shown.slice(0, 100).map((r) => r.id), [shown]);
  const listed = usePreviews(shownIds, false);
  const pickedIds = React.useMemo(() => [...picked], [picked]);
  const pickedPreview = usePreviews(pickedIds, true);

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
    <RecWorld label="RFQ packages">
      <PageHead
        title="RFQ packages"
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
                  records to pick from
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
              <b>No RFQ packages</b>
              <span>Pick the records to ask a supplier about, below. The package asks for each part, with its specs, quantity and CAD.</span>
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
                  const line = pickerLine(r, listed.byId.get(r.id));
                  const flags = r.is_stale ? " · out of date" : "";
                  return (
                    <div className={cx("pkrow", on && "on")} key={r.id}>
                      <button type="button" className="pkbtn" role="checkbox" aria-checked={on} aria-label={`Include ${r.filename}, ${line.what}, #${short(r.id)}`} onClick={() => toggle(r.id)}>
                        <span className="box" aria-hidden="true" />
                        <span className="th" aria-hidden="true">
                          <Glyph size={20} />
                        </span>
                        <span style={{ minWidth: 0 }}>
                          <b>{r.filename}</b>
                          <small>
                            {line.what}
                            {flags} · #{short(r.id)}
                          </small>
                        </span>
                      </button>
                      <span className="c num">{line.price}</span>
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
                  {list.more ? "+" : ""} · prices are ScaleCAD’s, at each part’s quantity · Open keeps your selection
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
        <PackageSheet key={pkgId} id={pkgId} toast={toast} canEdit={canEdit} onChanged={() => void loadPkgs()} />
      ) : (
        <Builder
          chosen={chosen}
          missing={missing.length}
          parts={parts}
          previews={pickedPreview.byId}
          requester={pickedPreview.requester ?? listed.requester}
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
  const link = p as RfqPackageSummary & { share_status?: LinkStatus | null };
  return (
    <div className={cx("pkrow pgr", on && "on")}>
      <button type="button" className="pkbtn pgb" onClick={onOpen} aria-pressed={on}>
        <span className="th" aria-hidden="true">
          <FileIcon />
        </span>
        <span style={{ minWidth: 0 }}>
          <b>{p.title || "RFQ package"}</b>
          <small>
            {plural(p.item_count, "part")}
            {p.supplier_name ? ` · ${p.supplier_name}` : ""} · {stampUtc(p.created_at)}
          </small>
        </span>
      </button>
      <Chip tone={link.share_status === "active" ? "ok" : "unk"}>{link.share_status === "active" ? "Link on" : "Not sent"}</Chip>
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

function isoToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function Builder({
  chosen,
  missing,
  parts,
  previews,
  requester,
  canEdit,
  onBuild,
}: {
  chosen: CostDecisionSummary[];
  missing: number;
  parts: number;
  previews: Map<string, PackagePreviewItem>;
  requester: Requester | null;
  canEdit: boolean;
  onBuild: (i: Omit<Parameters<typeof buildPackage>[0], "ids">) => Promise<void>;
}) {
  const n = chosen.length + missing;
  const first = chosen[0] ?? null;
  const auto = n === 1 && first ? `${first.filename} · RFQ` : n ? `${parts > 1 ? `${parts} parts` : plural(n, "part")} · RFQ` : "";
  const [title, setTitle] = React.useState<string | null>(null);
  const [supplier, setSupplier] = React.useState("");
  const [note, setNote] = React.useState("");
  const [replyBy, setReplyBy] = React.useState("");
  const [cad, setCad] = React.useState(true);
  const [cost, setCost] = React.useState(false);
  const [who, setWho] = React.useState<{ name: string; company: string; email: string } | null>(null);
  const [qty, setQty] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const t = title ?? auto;
  const off = !n || busy || !canEdit;
  const asker = who ?? { name: requester?.name ?? "", company: requester?.company ?? "", email: requester?.email ?? "" };
  const qtyOf = (id: string) => qty[id] ?? (previews.get(id)?.quantity != null ? String(previews.get(id)?.quantity) : "");
  const cadKept = chosen.filter((r) => previews.get(r.id)?.cad_kept === true).length;
  const cadMissing = chosen.filter((r) => previews.get(r.id)?.cad_kept === false).length;
  const noQty = chosen.filter((r) => !qtyOf(r.id).trim()).length;
  const notApproved = chosen.filter((r) => r.approval_status !== "approved").length;
  const stale = chosen.filter((r) => r.is_stale).length;

  const build = async () => {
    if (off) return;
    const quantities: Record<string, number> = {};
    for (const r of chosen) {
      const v = qtyOf(r.id).trim();
      if (!v) continue;
      if (!/^\d+$/.test(v) || Number(v) < 1 || Number(v) > 10_000_000) {
        setErr(`${r.filename}: the quantity is a whole number from 1 to 10,000,000.`);
        return;
      }
      quantities[r.id] = Number(v);
    }
    if (replyBy && replyBy < isoToday()) {
      setErr("The reply-by date has passed. Pick today or later.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await onBuild({ title: t, supplier, note, cad, cost, replyBy, requestedBy: asker, quantities });
    } catch (e) {
      setErr(errorText(e, "The package wasn't built."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <RecSheet label="The package">
      <div className="top">
        <h2 className="stitle">New RFQ package</h2>
        <p className="smeta">{n === 1 && first ? first.filename : n ? `${plural(n, "record")} from ${plural(parts, "part")}` : "No records selected"}</p>
        <div className="figs">
          <div className="fig">
            <span>Parts</span>
            <b className="num">{n}</b>
            <small>to quote</small>
          </div>
          <div className="fig">
            <span>CAD</span>
            <b className="num">{!cad ? "—" : chosen.length && cadKept + cadMissing < chosen.length ? "…" : `${cadKept} of ${chosen.length}`}</b>
            <small>{cad ? "files ScaleCAD kept" : "Not included"}</small>
          </div>
          <div className="fig">
            <span>Our cost</span>
            <b className={cx("t", cost && "warn")}>{cost ? "Included" : "Not included"}</b>
            <small>{cost ? "The supplier sees it" : "Stays with you"}</small>
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
          <div className="pk-two">
            <label className="field">
              Reply by
              <input type="date" min={isoToday()} value={replyBy} onChange={(e) => setReplyBy(e.target.value)} disabled={!canEdit} />
            </label>
            <label className="field">
              Requested by
              <input type="text" placeholder="Your name" value={asker.name} maxLength={200} onChange={(e) => setWho({ ...asker, name: e.target.value })} disabled={!canEdit} />
            </label>
          </div>
          <div className="pk-two">
            <label className="field">
              Company
              <input type="text" placeholder="Your company" value={asker.company} maxLength={200} onChange={(e) => setWho({ ...asker, company: e.target.value })} disabled={!canEdit} />
            </label>
            <label className="field">
              Email
              <input type="email" placeholder="Where the supplier replies" value={asker.email} maxLength={200} onChange={(e) => setWho({ ...asker, email: e.target.value })} disabled={!canEdit} />
            </label>
          </div>
          <label className="field">
            Note to the supplier
            <textarea placeholder="Releases, tolerances, delivery" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} disabled={!canEdit} />
          </label>
        </div>

        {chosen.length ? (
          <>
            <div className="gh">
              <span>Parts and quantities</span>
              <span>the supplier quotes these</span>
            </div>
            <div className="pk-parts">
              {chosen.map((r) => {
                const p = previews.get(r.id);
                const from = p?.quantity_source ? QTY_FROM[p.quantity_source] : null;
                return (
                  <div className="pk-part" key={r.id}>
                    <span style={{ minWidth: 0 }}>
                      <b>{r.filename}</b>
                      <small>
                        {[p?.material, p?.specs.filter((x) => !x.startsWith("Supplier must hold")).join(" · ") || null, p ? (p.cad_kept ? "CAD kept" : p.cad_kept === false ? "no CAD kept" : null) : null].filter(Boolean).join(" · ") || "Reading the part…"}
                      </small>
                      {from && !qty[r.id] ? <small>Quantity from {from}</small> : null}
                    </span>
                    <label className="pk-q">
                      <span className="sr">Quantity for {r.filename}</span>
                      <input type="text" inputMode="numeric" placeholder="Qty" value={qtyOf(r.id)} onChange={(e) => setQty({ ...qty, [r.id]: e.target.value })} disabled={!canEdit} />
                    </label>
                  </div>
                );
              })}
            </div>
          </>
        ) : null}

        <div className="pk-fields">
          <label className="chk">
            <input type="checkbox" checked={cad} onChange={(e) => setCad(e.target.checked)} disabled={!canEdit} />
            <span>
              Include the CAD files
              <small>{chosen.length && cadKept + cadMissing === chosen.length ? `ScaleCAD kept the file for ${cadKept} of ${plural(chosen.length, "part")}.` : "The file you checked, for each part ScaleCAD kept it for."}</small>
            </span>
          </label>
          <label className="chk">
            <input type="checkbox" checked={cost} onChange={(e) => setCost(e.target.checked)} disabled={!canEdit} />
            <span>
              Include our cost estimate (the supplier will see it)
              <small>Off unless you turn it on.</small>
            </span>
          </label>
          {cost ? (
            <p className="pk-costwarn" role="note">
              {COST_WARNING}
            </p>
          ) : null}
        </div>

        <div className="gh">
          <span>In the ZIP</span>
          <span>{n ? "one folder per part" : ""}</span>
        </div>
        <div className="files">
          {[
            ["Request for quote", "supplier-brief.pdf"],
            ["One line per part", "line-items.csv"],
            ["What is in it", "package_manifest.json"],
            ...(cad ? [["Each part's CAD file", "parts/…/file"]] : []),
            ...(cost
              ? [
                  ["Each part, our cost estimate", "should-cost-report.pdf"],
                  ["Each part, its price lines", "cost-drivers.csv"],
                ]
              : []),
          ].map(([k, f]) => (
            <div className="fl" key={k}>
              <FileIcon />
              <span>{k}</span>
              <b>{f}</b>
            </div>
          ))}
          {!cost ? (
            <div className="fl no">
              <FileIcon dashed />
              <span>Our cost estimate</span>
              <b>not included</b>
            </div>
          ) : null}
        </div>

        {notApproved || stale || missing || noQty || (cad && cadMissing) ? (
          <>
            <div className="gh">
              <span>Before you send</span>
              <span>not in the package</span>
            </div>
            {noQty ? (
              <div className="pk-warn">
                <i aria-hidden="true">!</i>
                <span>{plural(noQty, "part")} without a quantity. The supplier is asked without one.</span>
              </div>
            ) : null}
            {cad && cadMissing ? (
              <div className="pk-warn">
                <i aria-hidden="true">!</i>
                <span>{plural(cadMissing, "part")} without a kept CAD file. Attach it yourself.</span>
              </div>
            ) : null}
            {notApproved ? (
              <div className="pk-warn">
                <i aria-hidden="true">!</i>
                <span>{plural(notApproved, "record")} not approved in ScaleCAD. The supplier isn&apos;t told.</span>
              </div>
            ) : null}
            {stale ? (
              <div className="pk-warn">
                <i aria-hidden="true">!</i>
                <span>{plural(stale, "record")} out of date. Check the part again first.</span>
              </div>
            ) : null}
            {missing ? (
              <div className="pk-warn">
                <i aria-hidden="true">!</i>
                <span>{plural(missing, "selected record")} not in the loaded list; it&apos;s included by its id.</span>
              </div>
            ) : null}
          </>
        ) : null}
        {err ? (
          <p className="err2" role="alert">
            {err}
          </p>
        ) : null}
        <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap", alignItems: "center" }}>
          <button className={cx("btn ink", off && "off")} type="button" aria-disabled={off} onClick={() => void build()}>
            {busy ? "Building…" : `Build package (${n})`}
          </button>
          <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Not sent by ScaleCAD.</span>
        </div>
        <p className="ro-note" style={{ margin: "0 12px 12px" }}>
          {canEdit ? `${PACKAGE_NOTE} ${PACKAGE_PRIVATE}` : "Read only. Analysts and admins build packages."}
        </p>
      </div>
    </RecSheet>
  );
}

type PkgItem = RfqPackageDetail["items"][number] & {
  request?: { name?: string | null; quantity?: number | null; material?: string | null } | null;
  raw_cad?: { included: boolean; reason?: string; filename?: string } | null;
};
type Pkg = Omit<RfqPackageDetail, "items"> & {
  items: PkgItem[];
  share_url?: string | null;
  share_status?: LinkStatus | null;
  share_expires_at?: string | null;
  share_ended_at?: string | null;
};

function PackageSheet({ id, toast, canEdit, onChanged }: { id: string; toast: (m: string) => void; canEdit: boolean; onChanged: () => void }) {
  const [pkg, setPkg] = React.useState<Pkg | null>(null);
  const [err, setErr] = React.useState<{ text: string; notFound: boolean } | null>(null);
  const [dl, setDl] = React.useState<"idle" | "busy" | "done">("idle");
  const [sharing, setSharing] = React.useState(false);
  const [asking, setAsking] = React.useState(false);
  const load = React.useCallback(async () => {
    setErr(null);
    try {
      setPkg((await getPackage(id)) as Pkg);
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
            <NotFound title="Package not found" back={{ label: "Back to RFQ packages", href: R.packages }} onRetry={() => void load()}>
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
  const meta = (pkg.metadata ?? {}) as { raw_cad_requested?: boolean; include_cost_estimate?: boolean; reply_by?: string | null; requested_by?: Requester | null };
  const withCost = meta.include_cost_estimate === true;
  const cadKept = pkg.items.filter((i) => i.raw_cad?.included).length;
  const linkOn = pkg.share_status === "active" && pkg.share_url;
  const full = linkOn && typeof window !== "undefined" ? window.location.origin + pkg.share_url : null;
  const who = [meta.requested_by?.name, meta.requested_by?.company, meta.requested_by?.email].filter(Boolean).join(", ");
  return (
    <RecSheet label="The package">
      <div className="top">
        <h2 className="stitle" style={{ overflowWrap: "anywhere" }}>
          {pkg.title || "RFQ package"}
        </h2>
        <p className="smeta">Built {stampUtc(pkg.created_at)}</p>
        <div className="figs">
          <div className="fig">
            <span>Parts</span>
            <b className="num">{pkg.item_count}</b>
            <small>{cadKept ? `CAD for ${cadKept}` : "no CAD"}</small>
          </div>
          <div className="fig">
            <span>Our cost</span>
            <b className={cx("t", withCost && "warn")}>{withCost ? "Included" : "Not included"}</b>
            <small>{withCost ? "The supplier sees it" : "Stays with you"}</small>
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
          {canEdit ? (
            <button className="btn sm" type="button" onClick={() => setSharing(true)}>
              {linkOn ? "New link" : "Share"}
            </button>
          ) : null}
          <Link className="btn sm" href={R.packages}>
            New package
          </Link>
        </div>
        {linkOn ? (
          <div className="pk-link">
            <label className="field">
              Link · {linkEndText("active", pkg.share_expires_at ?? null)}
              <input type="text" readOnly value={full ?? ""} onFocus={(e) => e.currentTarget.select()} />
            </label>
            {asking ? (
              <Confirm
                label="Switch off link"
                question="Switch off the link? It stops working right away; anyone who opens it sees that it was switched off."
                action="Switch off"
                onConfirm={async () => {
                  try {
                    await unsharePackage(pkg.id);
                    toast("Link switched off");
                    setAsking(false);
                    setPkg((cur) => (cur ? { ...cur, share_url: null, share_status: "off" } : cur));
                    onChanged();
                  } catch (e) {
                    toast(errorText(e, "The link is still on."));
                    setAsking(false);
                  }
                }}
                onCancel={() => setAsking(false)}
              />
            ) : (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="btn sm"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(full ?? "");
                      toast("Link copied");
                    } catch {
                      toast("Copy didn't work. Select the link and copy it.");
                    }
                  }}
                >
                  Copy link
                </button>
                <a className="btn sm" href={full ?? "#"} target="_blank" rel="noopener noreferrer">
                  Open
                </a>
                {canEdit ? (
                  <button type="button" className="btn sm ghost" onClick={() => setAsking(true)}>
                    Switch off
                  </button>
                ) : null}
                <Link className="btn sm ghost" href={R.links}>
                  Share links
                </Link>
              </div>
            )}
          </div>
        ) : null}
        <p className="ro-note" style={{ margin: "0 12px" }}>
          {PACKAGE_NOTE} {PACKAGE_PRIVATE}
        </p>
        <div className="kv ev" style={{ marginTop: 6 }}>
          <span>Requested by</span>
          <b>{who || "Not given"}</b>
          <span>Reply by</span>
          <b>{meta.reply_by ? new Date(`${meta.reply_by}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "Not given"}</b>
        </div>
        <div className="gh">
          <span>Parts in this package</span>
          <span className="num">{pkg.items.length}</span>
        </div>
        <div>
          {pkg.items.map((i) => (
            <Link key={i.decision.id} className="mr2" href={R.record(i.decision.id)}>
              <span style={{ minWidth: 0 }}>
                {i.request?.name || i.decision.filename}
                <small style={{ display: "block" }}>
                  {[i.request?.material, i.request?.quantity != null ? `quantity ${num(i.request.quantity)}` : "no quantity", i.raw_cad?.included ? "CAD included" : "no CAD", `#${short(i.decision.id)}`].filter(Boolean).join(" · ")}
                </small>
              </span>
              <span className="o">Open</span>
            </Link>
          ))}
        </div>
        {pkg.warnings.length ? (
          <>
            <div className="gh">
              <span>For you</span>
              <span>not in the package</span>
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
          <span>In the ZIP</span>
          <span />
        </div>
        <div className="kv ev">
          <span>Brief</span>
          <b>supplier-brief.pdf and .md, line-items.csv, package_manifest.json</b>
          <span>CAD</span>
          <b>{cadKept ? `For ${plural(cadKept, "part")}` : meta.raw_cad_requested ? "Asked for; ScaleCAD has none of these files" : "Not asked for"}</b>
          <span>Our cost</span>
          <b>{withCost ? "Included: should-cost-report.pdf and cost-drivers.csv per part" : "Not included"}</b>
        </div>
      </div>
      {sharing ? (
        <ShareDialog
          target={{ kind: "package", id: pkg.id, name: pkg.title || "RFQ package" }}
          pkg={{ parts: pkg.item_count, cadParts: cadKept, hasCost: withCost }}
          current={linkOn ? { expiresAt: pkg.share_expires_at ?? null } : null}
          create={async (link) => {
            const m = await sharePackage(pkg.id, link);
            setPkg((cur) => (cur ? { ...cur, share_url: m.share_url, share_status: "active", share_expires_at: m.share_expires_at ?? null } : cur));
            onChanged();
            return m;
          }}
          onClose={() => setSharing(false)}
        />
      ) : null}
    </RecSheet>
  );
}
