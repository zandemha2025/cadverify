"use client";

/**
 * Machines and printers (board O9). The org's declared machines as tiles with
 * the work area drawn to scale and the hours of work the checked parts put on
 * each (GET /machine-inventory/load); the selected one opens in the right sheet.
 * Add, edit, delete (confirmed), CSV import and template, catalog prefill, and
 * the shop's in-house operations. `?add=1` opens the add form and
 * `?machine=<id>` selects a machine (the search palette links to both).
 */
import * as React from "react";
import {
  countMachines,
  deleteMachine,
  importMachinesCsv,
  listMachines,
  machineImportTemplate,
  type MachineImportSummary,
  type OwnedMachine,
} from "@/lib/verify/machine-api";
import Link from "next/link";
import { R, TABS } from "../routes";
import { Content, Empty, Loading, PageHead, Panel, Sheet, cx } from "../ui";
import { Banner, LaborFact, RateCardChip, ShopWorld, useLaborRate, usePartRecords, useRateCard, useToast } from "./common";
import { MachineDialog } from "./machine-dialog";
import { MachineSheet } from "./machine-sheet";
import { downloadText, getMachineLoad, getShopCapabilities, putShopCapabilities, type MachineLoad, type ShopLoad } from "./shop-api";
import { SpecCaps } from "./spec-caps";
import { SHOP_OPS, envelopeOf, hoursShort, isoBox, loadFor, loadTile, machineName, machineStatus, opOn, opSavedNote, tileSub, toggleOp } from "./shop-derive";
import { BatchEntryButton, batchEntryNote, useBatchAccess } from "../many/catalog-entry";
import { useUnits } from "../units/use-units";
import { UnitSwitch } from "../units/unit-switch";

type DialogState = { mode: "add"; process?: string } | { mode: "edit"; machine: OwnedMachine } | null;
type BannerState =
  | { kind: "import"; s: MachineImportSummary }
  | { kind: "importError"; msg: string }
  | { kind: "template" }
  | { kind: "templateError"; msg: string }
  | null;

function setQuery(id: string | null) {
  const url = new URL(window.location.href);
  url.searchParams.delete("add");
  if (id) url.searchParams.set("machine", id);
  else url.searchParams.delete("machine");
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}`);
}

export function MachinesScreen() {
  const [machines, setMachines] = React.useState<OwnedMachine[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [sel, setSel] = React.useState<string | null>(null);
  const [dialog, setDialog] = React.useState<DialogState>(null);
  const [banner, setBanner] = React.useState<BannerState>(null);
  const [busyCsv, setBusyCsv] = React.useState(false);
  const wanted = React.useRef<string | null>(null);
  const csvRef = React.useRef<HTMLInputElement>(null);
  const sheetRef = React.useRef<HTMLSpanElement>(null);
  const [toast, showToast] = useToast();
  const rc = useRateCard();
  // One request per load (GET /cost-decisions/latest-per-part): the newest record of each
  // part, with the details the labor rate reads; no per-record reads.
  const recs = usePartRecords(6);
  const labor = useLaborRate(rc, recs.data?.parts ?? null, recs.data?.details ?? null);
  // The hours of work the checked parts put on each machine (one org-scoped read).
  const [shopLoad, setShopLoad] = React.useState<ShopLoad | null>(null);
  const [workError, setWorkError] = React.useState<string | null>(null);
  const [workN, setWorkN] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    setWorkError(null);
    getMachineLoad().then(
      (l) => live && setShopLoad(l),
      (e) => live && setWorkError(e instanceof Error ? e.message : "Couldn't load the machine time."),
    );
    return () => {
      live = false;
    };
  }, [workN]);
  const reloadLoad = () => setWorkN((x) => x + 1);

  const load = React.useCallback(async () => {
    setLoadError(null);
    try {
      const page = await listMachines();
      setMachines(page.machines);
      return page.machines;
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Couldn't load machines.");
      setMachines(null);
      return null;
    }
  }, []);

  // Deep links: ?add=1 opens the add form, ?machine=<id> selects that machine.
  React.useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    wanted.current = q.get("machine");
    if (q.get("add") === "1") {
      setDialog({ mode: "add" });
      setQuery(wanted.current);
    }
    void load().then((list) => {
      if (!list) return;
      const want = wanted.current;
      if (want && list.some((m) => m.id === want)) setSel(want);
      else {
        if (want) {
          showToast("That machine isn't in your shop.");
          setQuery(list[0]?.id ?? null);
        }
        setSel(list[0]?.id ?? null);
      }
    });
  }, [load, showToast]);

  const pick = (id: string) => {
    setSel(id);
    setQuery(id);
    if (window.matchMedia("(max-width: 900px)").matches) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      requestAnimationFrame(() => sheetRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }));
    }
  };

  const onCsv = async (file: File) => {
    setBusyCsv(true);
    setBanner(null);
    try {
      const s = await importMachinesCsv(file);
      setBanner({ kind: "import", s });
      if (s.imported > 0) {
        const list = await load();
        if (list && !sel) setSel(list[0]?.id ?? null);
        recs.reload();
        reloadLoad();
      }
    } catch (e) {
      setBanner({ kind: "importError", msg: e instanceof Error ? e.message : "Import failed." });
    } finally {
      setBusyCsv(false);
    }
  };

  const onTemplate = async () => {
    try {
      downloadText(await machineImportTemplate(), "machines.csv");
      setBanner({ kind: "template" });
    } catch (e) {
      setBanner({ kind: "templateError", msg: e instanceof Error ? e.message : "Couldn't download the template." });
    }
  };

  const selected = (machines ?? []).find((m) => m.id === sel) ?? null;
  const total = machines ? countMachines(machines) : null;
  const rated = machines ? machines.filter((m) => m.hourly_rate_usd != null).length : null;

  const onDelete = async () => {
    if (!selected) return;
    const name = machineName(selected);
    const idx = (machines ?? []).findIndex((m) => m.id === selected.id);
    await deleteMachine(selected.id);
    const list = await load();
    const next = list?.[Math.min(idx, (list?.length ?? 1) - 1)]?.id ?? null;
    setSel(next);
    setQuery(next);
    recs.reload();
    reloadLoad();
    showToast(`Removed ${name}. Older decisions are marked for re-costing.`);
  };

  const onSaved = async (m: OwnedMachine, mode: "add" | "edit") => {
    setDialog(null);
    await load();
    setSel(m.id);
    setQuery(m.id);
    recs.reload();
    reloadLoad();
    showToast(`${mode === "add" ? "Added" : "Saved"} ${machineName(m)}. Older decisions are marked for re-costing.`);
  };

  const actions = (
    <>
      <button className="btn ink sm" type="button" onClick={() => setDialog({ mode: "add" })}>
        Add machine
      </button>
      <button className="btn sm" type="button" onClick={() => csvRef.current?.click()} disabled={busyCsv}>
        {busyCsv ? "Importing…" : "Import CSV"}
      </button>
      <button className="btn sm" type="button" onClick={onTemplate}>
        Download template
      </button>
    </>
  );

  const fig = (v: number | null) => (loadError ? "—" : v == null ? "…" : v);
  const workHours = shopLoad ? shopLoad.machines.reduce<number | null>((s, m) => (m.hours != null ? (s ?? 0) + m.hours : s), null) : null;
  const tabs = TABS.shop.map((t) => (t.href === R.shop && total != null ? { ...t, count: total } : t));

  return (
    <ShopWorld label="Your machines">
      <PageHead
        title="Machines and printers"
        actions={actions}
        meta={[
          <>
            Machines <b className="num">{fig(total)}</b>
          </>,
          <>
            Rates declared <b className="num">{fig(rated)}</b>
          </>,
          <>
            Rate card <RateCardChip rc={rc} action={{ label: "Open Rates", href: R.rates }} />
          </>,
          <LaborFact key="l" src={labor} />,
        ]}
        tabs={tabs}
        tabsLabel="Your shop"
        tabsAside={
          <span className="sizes">
            Sizes <UnitSwitch className="unit-switch" />
          </span>
        }
      />
      <input
        ref={csvRef}
        type="file"
        accept=".csv,text/csv"
        aria-label="Choose a machines CSV to import"
        tabIndex={-1}
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void onCsv(f);
        }}
      />
      <Content>
        {banner?.kind === "import" ? (
          <Banner tone={banner.s.errors.length ? "warn" : "ok"} onDismiss={() => setBanner(null)}>
            <b>
              Import complete: {banner.s.imported} imported · {banner.s.skipped} skipped · {banner.s.total} total
            </b>
            {banner.s.imported > 0 ? <> Older decisions are marked for re-costing.</> : null}
            {banner.s.errors.length ? (
              <ul>
                {banner.s.errors.map((er, i) => (
                  <li key={i}>
                    {er.line != null ? `Line ${er.line}: ` : ""}
                    {er.reason}
                  </li>
                ))}
              </ul>
            ) : null}
          </Banner>
        ) : null}
        {banner?.kind === "importError" ? (
          <Banner tone="bad" alert onDismiss={() => setBanner(null)}>
            <b>Import failed.</b> {banner.msg} Existing machines weren&apos;t changed.
          </Banner>
        ) : null}
        {banner?.kind === "template" ? (
          <Banner tone="ok" onDismiss={() => setBanner(null)}>
            <b>machines.csv template downloaded.</b> Existing machines aren&apos;t removed on import.
          </Banner>
        ) : null}
        {banner?.kind === "templateError" ? (
          <Banner tone="bad" alert onDismiss={() => setBanner(null)}>
            <b>Couldn&apos;t download the template.</b> {banner.msg}
          </Banner>
        ) : null}
        {loadError ? (
          <Banner
            tone="bad"
            alert
            actions={
              <button className="btn sm" type="button" onClick={() => void load()}>
                Retry
              </button>
            }
          >
            <b>Couldn&apos;t load machines.</b> {loadError}
          </Banner>
        ) : machines == null ? (
          <div className="panel">
            <Loading rows={3} label="Loading machines" />
          </div>
        ) : machines.length === 0 ? (
          <section className="panel">
            <Empty title="No machines" actions={actions}>
              Parts are checked against typical machines until you add yours. Add them before a batch of parts: the run sorts every part by the machines here, and
              a machine from the catalog, added as the maker specifies it, can already say yes.
            </Empty>
          </section>
        ) : (
          <>
          {shopLoad ? <LoadSummary load={shopLoad} hours={workHours} /> : null}
          <div className="mgrid">
            {machines.map((m) => (
              <MachineTile key={m.id} m={m} on={m.id === sel} onPick={() => pick(m.id)} load={shopLoad ? loadFor(shopLoad.machines, machineName(m)) ?? loadFor(shopLoad.machines, m.name ?? "") : undefined} />
            ))}
            <AddTile onPick={() => setDialog({ mode: "add", process: "fdm" })} />
          </div>
          </>
        )}
        {machines && machines.length > 0 ? <BatchOnMachines n={total ?? machines.length} /> : null}
        <ShopOps onSaved={() => recs.reload()} />
      </Content>
      <Sheet label="Machine details" style={{ bottom: 20 }}>
        <span ref={sheetRef} aria-hidden="true" style={{ display: "block", height: 0 }} />
        {selected ? (
          <MachineSheet
            m={selected}
            records={recs.data?.parts ?? null}
            recordsError={recs.error}
            onRetryRecords={recs.reload}
            load={shopLoad ? { qty: shopLoad.quantity, machine: loadFor(shopLoad.machines, machineName(selected)) ?? loadFor(shopLoad.machines, selected.name ?? ""), other: shopLoad.other_decisions } : null}
            loadError={workError}
            onRetryLoad={reloadLoad}
            rc={rc}
            onEdit={() => setDialog({ mode: "edit", machine: selected })}
            onDelete={onDelete}
          />
        ) : (
          <div className="top">
            <h2 className="stitle">No machine selected</h2>
            <p className="smeta">{loadError ? "Machines didn’t load." : machines && machines.length === 0 ? "Typical machines are used until you add yours." : machines ? "Pick a machine to see its spec." : "Loading…"}</p>
          </div>
        )}
      </Sheet>
      {dialog ? (
        <MachineDialog
          key={dialog.mode === "edit" ? dialog.machine.id : `add-${dialog.process ?? ""}`}
          mode={dialog.mode}
          machine={dialog.mode === "edit" ? dialog.machine : null}
          presetProcess={dialog.mode === "add" ? dialog.process : undefined}
          onClose={() => setDialog(null)}
          onSaved={onSaved}
        />
      ) : null}
      {toast}
    </ShopWorld>
  );
}

function MachineTile({ m, on, onPick, load }: { m: OwnedMachine; on: boolean; onPick: () => void; load?: MachineLoad | null }) {
  const { unit } = useUnits();
  const env = envelopeOf(m, unit);
  const st = machineStatus(m);
  const box = env ? isoBox(env.w, env.d, env.h) : null;
  return (
    <button type="button" className={cx("mt", on && "on", load !== undefined && "has-ld")} onClick={onPick} aria-pressed={on}>
      <b>{machineName(m)}</b>
      <small>{tileSub(m)}</small>
      {load !== undefined ? <small className={cx("mt-ld num", !load?.parts && "none")}>{loadTile(load)}</small> : null}
      {box ? (
        <svg height="128" viewBox="0 0 300 150" aria-hidden="true">
          <polygon points={box.floor} fill="#E3E7EC" fillOpacity="0.85" />
          <path d={box.back} stroke="#AEB5BE" strokeWidth="1" strokeDasharray="3 4" fill="none" />
          <path d={box.front} stroke="#5F656E" strokeWidth="1.4" fill="none" strokeLinejoin="round" />
        </svg>
      ) : (
        <svg height="128" viewBox="0 0 300 150" aria-hidden="true">
          <rect x="95" y="30" width="110" height="90" rx="10" fill="none" stroke="#C3C8CE" strokeWidth="1.4" strokeDasharray="4 4" />
        </svg>
      )}
      <span className="foot">
        <span className="num">{env ? env.text : "Work area not declared"}</span>
        <span className={cx("chip", st.rated ? "c-ok" : "c-warn")}>
          <i aria-hidden="true" />
          {st.rated ? "Rate declared" : "No rate"}
        </span>
      </span>
    </button>
  );
}

/** One line over the tiles: the work the checked parts put on your machines, and parts recorded in-house that no machine of yours clears now. */
function LoadSummary({ load, hours }: { load: ShopLoad; hours: number | null }) {
  const on = load.machines.filter((m) => m.parts).length;
  const lost = load.decided_unplaced_count;
  const names = load.decided_unplaced.map((p) => p.file_name).filter(Boolean).slice(0, 3).join(", ");
  return (
    <p className="ld-sum" aria-live="polite">
      {hours != null && on ? (
        <>
          Work from checked parts: <b className="num">{hoursShort(hours)}</b> on {on === 1 ? "1 machine" : `${on} machines`}, from each part’s newest check
        </>
      ) : (
        "No checked part lands on these machines yet"
      )}
      {lost ? (
        <>
          {" "}
          · {lost === 1 ? "1 part" : `${lost} parts`} recorded in-house {lost === 1 ? "doesn’t" : "don’t"} fit any of them on {lost === 1 ? "its" : "their"} newest check{names ? `: ${names}${lost > 3 ? " and more" : ""}` : ""}
        </>
      ) : null}
      .
    </p>
  );
}

function AddTile({ onPick }: { onPick: () => void }) {
  const { unit } = useUnits();
  const box = isoBox(256, 256, 256);
  return (
    <button type="button" className="mt add" onClick={onPick}>
      <b>Add a printer</b>
      <small>From the catalog or blank</small>
      <svg height="128" viewBox="0 0 300 150" aria-hidden="true">
        <polygon points={box.floor} fill="#E3E7EC" fillOpacity="0.5" />
        <path d={box.back} stroke="#AEB5BE" strokeWidth="1" strokeDasharray="3 4" fill="none" />
        <path d={box.front} stroke="#8A9099" strokeWidth="1.4" strokeDasharray="4 4" fill="none" strokeLinejoin="round" />
      </svg>
      <span className="foot">
        <span className="num">e.g. {unit === "in" ? "10.08 × 10.08 × 10.08 in" : "256 × 256 × 256 mm"}</span>
        <span className="chip c-unk">
          <i aria-hidden="true" />
          Not added
        </span>
      </span>
    </button>
  );
}

/** "Across the shop": the shop-level operations the engine asks for by name. */
function ShopOps({ onSaved }: { onSaved: () => void }) {
  const [ops, setOps] = React.useState<Record<string, unknown> | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState<string | null>(null);
  const [note, setNote] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    setError(null);
    getShopCapabilities().then(
      (r) => live && setOps(r.ops ?? {}),
      (e) => live && setError(e instanceof Error ? e.message : "Couldn't load shop operations.")
    );
    return () => {
      live = false;
    };
  }, [n]);

  const toggle = async (key: string, label: string) => {
    if (!ops || saving) return;
    const next = toggleOp(ops, key);
    setSaving(key);
    setNote(null);
    try {
      const r = await putShopCapabilities(next);
      setOps(r.ops ?? next);
      setNote({ ok: true, text: `${opSavedNote(label, r.ops ?? next, key)} Older decisions are marked for re-costing.` });
      onSaved();
    } catch (e) {
      setNote({ ok: false, text: `Couldn't save: ${e instanceof Error ? e.message : "try again."}` });
    } finally {
      setSaving(null);
    }
  };

  // One op set to in-house (true), sent out / not held (false) or not said (absent).
  const setKey = async (key: string, value: boolean | undefined, label: string) => {
    if (!ops || saving) return;
    const next = { ...ops };
    if (value === undefined) delete next[key];
    else next[key] = value;
    setSaving(key);
    setNote(null);
    try {
      const r = await putShopCapabilities(next);
      setOps(r.ops ?? next);
      const said = value === undefined ? "not said" : value ? "declared" : "declared not here";
      setNote({ ok: true, text: `${label}: ${said}. Older decisions are marked for re-costing.` });
      onSaved();
    } catch (e) {
      setNote({ ok: false, text: `Couldn't save: ${e instanceof Error ? e.message : "try again."}` });
    } finally {
      setSaving(null);
    }
  };

  return (
    <Panel
      title="Across the shop"
      note={
        <>
          Labor rate is set in <Link href={R.rates}>Rates</Link>
        </>
      }
    >
      {error ? (
        <div style={{ padding: "0 16px 14px" }}>
          <Banner
            tone="bad"
            alert
            actions={
              <button className="btn sm" type="button" onClick={() => setN((x) => x + 1)}>
                Retry
              </button>
            }
          >
            <b>Couldn&apos;t load shop operations.</b> {error}
          </Banner>
        </div>
      ) : (
        <div className="ops" role="group" aria-label="Done in-house">
          <span style={{ fontSize: 13, color: "var(--ink2)", marginRight: 4 }} aria-hidden="true">
            Done in-house
          </span>
          {SHOP_OPS.map(([key, label]) => {
            const on = ops ? opOn(ops, key) : false;
            return (
              <button
                key={key}
                type="button"
                className={cx("tog2", on && "on")}
                aria-pressed={on}
                aria-disabled={!ops || saving != null}
                onClick={() => void toggle(key, label)}
              >
                {saving === key ? "Saving…" : label}
              </button>
            );
          })}
        </div>
      )}
      <p className={cx("fh")} aria-live="polite" style={{ margin: "-6px 16px 12px", color: note && !note.ok ? "var(--bad)" : undefined }}>
        {note
          ? note.text
          : "Stress relief and sintering, a metal printer's own steps, count as done in-house until you turn them off (sent out). HIP and grinding count only when on."}
      </p>
      {!error ? <SpecCaps ops={ops} saving={saving} onSet={(k, v, l) => void setKey(k, v, l)} /> : null}
    </Panel>
  );
}

/** With machines declared: check a batch of parts against them (the catalog run). */
function BatchOnMachines({ n }: { n: number }) {
  const a = useBatchAccess();
  if (a.kind === "personal" || a.kind === "loading") return null;
  return (
    <section className="panel" aria-label="Check a batch on these machines">
      <div className="ph">
        <h2>
          Check a batch of parts on {n === 1 ? "this machine" : `these ${n} machines`}
        </h2>
        <span>{batchEntryNote(a)}</span>
      </div>
      <p style={{ margin: "0 16px 6px", color: "var(--ink2)", fontSize: 13.5 }}>
        Each part is sorted: make in-house here, buy outside, needs a new machine, or can’t be made as drawn, with machine time and material for each.
      </p>
      <div style={{ display: "flex", gap: 8, padding: "6px 16px 14px", flexWrap: "wrap" }}>
        <BatchEntryButton className="btn ink sm" />
      </div>
    </section>
  );
}
