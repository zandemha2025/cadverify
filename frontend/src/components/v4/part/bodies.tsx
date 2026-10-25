"use client";

/**
 * Bodies: a file that holds several bodies (a weldment, a part with its fixture,
 * parts saved together), body by body. The list lights each body on the part in
 * 3D; the body check (POST /parts/{hash}/bodies) gives every body its own verdict
 * and price, or, for a weldment, its stock and material; any body opens as a part
 * of its own (a copy ScaleCAD makes, so its check uses no check).
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { bodyAsPart, checkBodies, contactsNoteToShow, expandFaces, isMultiBody, type BodiesCheck, type BodyInfo, type PartType } from "@/lib/verify/bodies";
import { ownedProcessesFrom } from "@/lib/verify/machine-api";
import { R } from "../routes";
import { cx } from "../ui";
import { methodName, money, plural, qtyWord, trimNum } from "./model";
import { KIND_TITLE, bodyRows, bodyTitle, designOf, materialNote, metaLine, priceOf, quantitiesOf, totalOf, weldmentLines } from "./bodies-model";
import { SheetTop, type FigItem } from "./sheet-bits";
import { startCheck } from "./store";
import type { PartData } from "./ctx";
import type { ViewerHighlight } from "./viewer";

export const BODY_COLOR = "#2E6BE6";

export interface BodiesState {
  pt: PartType & { bodies: BodyInfo[] };
  open: boolean;
  setOpen: (o: boolean) => void;
  pick: number;
  setPick: (id: number) => void;
  check: BodiesCheck | null;
  running: boolean;
  error: string | null;
  run: () => void;
  opening: number | null;
  openBody: (id: number) => void;
  openError: string | null;
}

/** The bodies of the part on screen, and their check. Null for a one-body file. */
export function useBodies(data: PartData, opts: { sourceKept: boolean | null; qs: number[]; checking: boolean }): BodiesState | null {
  const router = useRouter();
  const pt = data.validation?.part_type ?? null;
  const multi = isMultiBody(pt) ? pt : null;
  const [open, setOpen] = React.useState(false);
  const [pick, setPick] = React.useState(1);
  const [check, setCheck] = React.useState<BodiesCheck | null>(null);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [opening, setOpening] = React.useState<number | null>(null);
  const [openError, setOpenError] = React.useState<string | null>(null);
  const asked = React.useRef<string | null>(null);
  const material = data.cost?.material_class ?? null;
  const key = data.key;
  // A file of several bodies opens on its bodies: the whole-file figures treat it as one block.
  React.useEffect(() => {
    if (multi && !opts.checking) setOpen(true);
  }, [!!multi, opts.checking]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = React.useCallback(() => {
    if (!key || !multi) return;
    setRunning(true);
    setError(null);
    checkBodies(key, { materialClass: material, qty: opts.qs.slice(0, 6), owned: ownedProcessesFrom(data.machines ?? []) })
      .then((c) => setCheck(c))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "The bodies weren’t checked."))
      .finally(() => setRunning(false));
  }, [key, multi, material, opts.qs, data.machines]);
  // Checked once the sheet is open and the file is kept (no upload, no check used).
  React.useEffect(() => {
    if (!open || !multi || !key || opts.checking || opts.sourceKept === false) return;
    const sig = `${key}|${material ?? ""}`;
    if (asked.current === sig) return;
    asked.current = sig;
    run();
  }, [open, multi, key, material, opts.checking, opts.sourceKept, run]);
  const openBody = React.useCallback(
    (id: number) => {
      if (!key) return;
      setOpening(id);
      setOpenError(null);
      bodyAsPart(key, id)
        .then((b) => {
          startCheck(b.file, { materialClass: check?.material_class ?? material ?? undefined });
          router.push(R.check);
        })
        .catch((e: unknown) => setOpenError(e instanceof Error ? e.message : "The body didn’t open."))
        .finally(() => setOpening(null));
    },
    [key, check?.material_class, material, router],
  );
  if (!multi) return null;
  // Once checked, the body check's own reading (a STEP file's product tree) is the one shown.
  const shown = check && isMultiBody(check.part_type) ? check.part_type : multi;
  return { pt: shown, open, setOpen, pick, setPick, check, running, error, run, opening, openBody, openError };
}

/** The picked body, lit on the part (faces of the check's own analysis mesh). */
export function bodyHighlight(b: BodiesState | null, aligned: boolean): ViewerHighlight | null {
  if (!b?.open || !aligned) return null;
  const body = b.pt.bodies.find((x) => x.id === b.pick);
  if (!body) return null;
  const faces = expandFaces(body.faces);
  return faces.length ? { faces, color: BODY_COLOR, region: null, label: String(body.id), kindClass: "k-support" } : null;
}

/** The HUD line on a multi-body part: what it holds, and the way to the bodies. */
export function BodiesChip({ b }: { b: BodiesState }) {
  return (
    <span className="bodies-hud">
      <span>{b.pt.summary}</span>
      <button className={cx("btn sm", b.open && "ink")} type="button" aria-pressed={b.open} onClick={() => b.setOpen(!b.open)}>
        {b.open ? "Body by body" : "See body by body"}
      </button>
    </span>
  );
}

export function BodiesSheet({ b, qs, aligned, has3d }: { b: BodiesState; qs: number[]; aligned: boolean; has3d: boolean }) {
  const quantities = quantitiesOf(b.check, qs);
  const [q, setQ] = React.useState<number>(quantities[0] ?? 1);
  React.useEffect(() => {
    if (!quantities.includes(q)) setQ(quantities[0] ?? 1);
  }, [quantities, q]);
  const pt = b.pt;
  const weldment = pt.kind === "weldment";
  // A STEP mesh whose touching solids merged: no list until the product tree is read.
  const provisional = !!pt.provisional;
  const rows = provisional ? [] : bodyRows(pt, b.check, q);
  const sel = pt.bodies.find((x) => x.id === b.pick) ?? pt.bodies[0];
  const total = totalOf(b.check, q);
  const figs: FigItem[] = [
    provisional
      ? { k: "Bodies", v: "Several", s: "from the product tree", tone: "warn" }
      : { k: "Bodies", v: String(pt.body_count), s: pt.designs && pt.designs < pt.body_count ? plural(pt.designs, "shape") : "all different" },
    weldment
      ? { k: "Joints", v: String(pt.joints?.count ?? 0), s: pt.joints ? `≈ ${Math.round(pt.joints.weld_length_mm_estimate).toLocaleString("en-US")} mm of weld, estimated` : "" }
      : {
          k: "Touching",
          v: String(pt.contacts?.length ?? 0),
          // Close pairs whose contact wasn't checked: "none found", not "none", and how many weren't checked.
          s: `${pt.contacts?.length ? "pairs of bodies" : pt.contacts_unchecked ? "none found" : "none"}${pt.contacts_unchecked?.pairs ? ` · ${pt.contacts_unchecked.pairs} not checked` : ""}`,
        },
    { k: weldment ? "Members’ material" : `Total at ${qtyWord(q)}`, v: total.value, s: total.note, tone: b.check ? undefined : "warn" },
  ];
  const mnote = materialNote(b.check);
  return (
    <>
      <SheetTop title={KIND_TITLE[pt.kind] ?? "Bodies"} meta={metaLine(pt, b.check)} figs={figs} />
      <div className="scroll">
        <div className="note" style={{ marginTop: 8 }}>
          <b>{pt.summary}</b>
          {contactsNoteToShow(pt) ? <span>{contactsNoteToShow(pt)}</span> : null}
          <span>
            {weldment
              ? "Each member is read as cut stock from its cross-section and length. The route is cut, prep, weld, finish."
              : "Each body is checked as its own part. The whole-file figures under the other questions treat the file as one block, which is not how it would be made."}
          </span>
          {pt.joints && weldment ? <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{pt.joints.words}</span> : null}
        </div>
        {b.error ? (
          <div className="note swap" role="alert">
            <b>The bodies weren’t checked</b>
            <span>{b.error}</span>
            <span>
              <button className="btn ink sm" type="button" onClick={b.run}>
                Try again
              </button>
            </span>
          </div>
        ) : !b.check ? (
          <div className="note swap" role="status">
            <b>{b.running ? "Checking each body…" : "Not checked body by body yet"}</b>
            <span>{b.running ? "The same engine as a single check, once per shape, from the file kept with this part. No check used." : "Every body checked as its own part, from the file kept with this part. No check used."}</span>
            {!b.running ? (
              <span>
                <button className="btn ink sm" type="button" onClick={b.run}>
                  Check each body
                </button>
              </span>
            ) : null}
          </div>
        ) : null}
        {mnote ? <p className="pmeta" style={{ margin: "6px 12px 0" }}>{mnote}</p> : null}
        {quantities.length > 1 && b.check && (!weldment || b.check.weldment?.cut_blanks) ? (
          <div className="gh">
            <span>Per file, at</span>
            <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
              {quantities.map((n) => (
                <button key={n} type="button" className={cx("btn sm", n === q && "ink")} aria-pressed={n === q} onClick={() => setQ(n)} style={{ height: 24, padding: "0 8px" }}>
                  {qtyWord(n)}
                </button>
              ))}
            </span>
          </div>
        ) : null}
        <div className="gh">
          <span>{weldment ? "Members" : "Bodies"}</span>
          <span>{has3d && aligned ? "pick one to see it on the part" : weldment ? "stock and material, each" : "each, as its own part"}</span>
        </div>
        {rows.map((r) => (
          <button key={r.id} type="button" className={cx("mr", r.id === sel?.id && "on")} aria-pressed={r.id === sel?.id} onClick={() => b.setPick(r.id)}>
            <span>
              <b>
                {r.title}
                {r.copyOf ? (
                  <span className="num" style={{ fontWeight: 500, color: "var(--ink3)" }}>
                    {" "}
                    · same as {r.copyOf}
                  </span>
                ) : null}
              </b>
              <small>{r.sub}</small>
            </span>
            <span className={`chip ${r.chip.cls}`}>
              <i />
              {r.chip.label}
            </span>
            <span className="c num" title={r.priceNote}>
              {r.price}
            </span>
          </button>
        ))}
        {sel && !provisional ? <BodyDetail b={b} body={sel} q={q} weldment={weldment} /> : null}
        {weldment ? (
          <>
            <div className="gh" style={{ marginTop: 6 }}>
              <span>Fabrication</span>
              <span>cut · prep · weld · finish</span>
            </div>
            <div className="lines">
              {weldmentLines(b.check, pt).map((l) => (
                <div className="ln" key={l.k} style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
                  <span>
                    <b style={{ display: "block", textAlign: "left" }}>{l.k}</b>
                    {l.note ? <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{l.note}</span> : null}
                  </span>
                  <b className="num" style={{ textAlign: "right" }}>
                    {l.v}
                  </b>
                </div>
              ))}
            </div>
            <div className="note">
              <b>Welding isn’t priced yet</b>
              <span>{b.check?.weldment?.words ?? "ScaleCAD doesn’t price welding yet. The members are shown with their stock; their material is priced once the bodies are checked."}</span>
            </div>
          </>
        ) : null}
        {pt.kind === "assembly" ? (
          <div className="note">
            <b>Fit and interference between the parts</b>
            <span>{b.check?.assembly?.words ?? "Fit, interference between the parts and quantities read from the product tree are in the assembly check, a pilot tool. The bodies here are checked one by one."}</span>
            <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <a className="btn sm" href="/contact">
                Talk to us
              </a>
              <Link className="btn sm" href={R.billing}>
                Plans
              </Link>
            </span>
          </div>
        ) : null}
        <p className="pmeta" style={{ margin: "8px 12px 12px" }}>
          {b.check?.basis ?? "Bodies are the file’s closed skins (a skin inside another is a sealed void); each body is checked with the same engine as a single check."}
          {b.check?.part_type?.source === "step_product_tree" ? " Bodies and names come from the file’s product tree." : ""}
        </p>
      </div>
    </>
  );
}

function BodyDetail({ b, body, q, weldment }: { b: BodiesState; body: BodyInfo; q: number; weldment: boolean }) {
  const d = designOf(b.check, body);
  const price = priceOf(d, q, weldment);
  const at = d?.by_quantity?.[String(q)];
  const top = d?.dfm?.top_issues?.[0];
  return (
    <div className="swap">
      <div className="gh">
        <span>
          {bodyTitle(body)}
          {body.copies > 1 ? ` · ${body.copies} of this shape` : ""}
        </span>
        <span />
      </div>
      {body.tree_path ? (
        <p className="mono" style={{ margin: "0 12px 2px", fontSize: 11.5, color: "var(--ink3)", overflowWrap: "anywhere" }}>
          {body.tree_path}
        </p>
      ) : null}
      <div className="kv">
        <span>Shape</span>
        <b>{body.shape}</b>
        <span>Size</span>
        <b className="num">{body.bbox_mm.map((n) => trimNum(n, 1)).join(" × ")} mm</b>
        <span>Volume</span>
        <b className="num">{body.closed ? `${Math.round(body.volume_mm3).toLocaleString("en-US")} mm³` : "not a closed solid"}</b>
        {d?.stock_material ? (
          <>
            <span>Weight</span>
            <b className="num">
              {trimNum(d.stock_material.mass_kg, 3)} kg {d.stock_material.material.toLowerCase()}
            </b>
            <span>Material</span>
            <b className="num">
              {money(d.stock_material.usd)} at {money(d.stock_material.usd_per_kg)}/kg
            </b>
          </>
        ) : null}
        {d?.processes ? (
          <>
            <span>Processes</span>
            <b className="num">
              {d.processes.can_make} of {d.processes.of} can make it
            </b>
          </>
        ) : null}
      </div>
      {weldment && d?.status === "ok" ? (
        <p style={{ margin: "4px 12px 0", color: "var(--ink2)", fontSize: 13 }}>
          {d.cut_blank?.[String(q)]
            ? `As a laser-cut blank on the sheet-metal route: ${price.value} each.`
            : `Cutting this member from ${(body.stock?.kind ?? "").includes("tube") ? "tube" : "stock"} isn’t priced yet.`}
          {at?.unit_cost_usd != null ? ` Made on its own as a finished part, the engine’s cheapest route is ${methodName(at.process)} at ${money(at.unit_cost_usd)} each; that isn’t how a weldment member is made.` : ""}
        </p>
      ) : null}
      {!weldment && at?.unit_cost_usd != null ? (
        <div className="note" style={{ marginTop: 4 }}>
          <b>
            {money(at.unit_cost_usd)} each · {methodName(at.process)}
            {at.material ? ` · ${at.material}` : ""}
          </b>
          <span>
            {at.quantity_each !== q ? `${qtyWord(at.quantity_each)} of this body for ${qtyWord(q)} ${q === 1 ? "file" : "files"} · ` : ""}
            {at.lead_days?.[0] != null && at.lead_days?.[1] != null ? `${Math.round(at.lead_days[0])}–${Math.round(at.lead_days[1])} days · ` : ""}
            typical rates
          </span>
        </div>
      ) : null}
      {d?.cots?.is_cots ? (
        <div className="note" style={{ marginTop: 4 }}>
          <b>Standard hardware: buy it</b>
          <span>
            {d.cots.kind}
            {d.cots.nominal_size ? ` ${d.cots.nominal_size}` : ""} · {money(d.cots.buy_price_usd)} each, a catalog estimate, not a quote
          </span>
        </div>
      ) : null}
      {d?.reason ? <p style={{ margin: "4px 12px 0", color: "var(--ink2)", fontSize: 13 }}>{d.reason}</p> : null}
      {top && !weldment ? <p style={{ margin: "4px 12px 0", color: "var(--ink2)", fontSize: 13 }}>{top.message}</p> : null}
      <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "8px 12px", flexWrap: "wrap" }}>
        <button className="btn sm" type="button" disabled={!body.closed || b.opening != null} onClick={() => b.openBody(body.id)} title={body.closed ? "A copy of this body as a part of its own; its check uses no check" : "Only a closed body can be checked on its own"}>
          {b.opening === body.id ? "Opening…" : "Open as its own part"}
        </button>
        <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Your machines, every finding and the full price; no check used.</span>
      </div>
      {b.openError ? (
        <p className="err" role="alert" style={{ margin: "0 12px 6px" }}>
          {b.openError}
        </p>
      ) : null}
    </div>
  );
}
