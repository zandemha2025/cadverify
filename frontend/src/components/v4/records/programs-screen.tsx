"use client";

/**
 * Programs (board P6): parts grouped into programs, each costed for a year as
 * the engine's pick at the declared yearly volume × that volume. A part counts
 * only when its volume is a priced quantity; otherwise the year is withheld,
 * never multiplied out from another quantity. Assign a part (or move it, after
 * a confirm), set its yearly volume (Enter or leaving the field saves), or
 * remove it (confirmed; its volume stays).
 *
 * Writes go through PUT /part-context/{part} with only the fields being changed
 * (program and/or annual_volume), so a part's service conditions and BOM link
 * are never touched from here.
 */
import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/ui/auth-provider";
import { canMutateWorkspace } from "@/lib/role-capabilities";
import { assignContext } from "@/lib/verify/program-api";
import { declaredPrograms, parseAnnualVolume, resolvedAnnualVolume, rowsInProgram, type PortfolioRow } from "@/lib/verify/program-rollup";
import { R, TABS } from "../routes";
import { Content, PageHead, cx } from "../ui";
import { errorText, patchPortfolio, usePortfolio } from "./api";
import { Confirm, Glyph, LoadFailed, NoneYet, RecSheet, RecWorld, Skeleton, useToast } from "./common";
import { money, num, plural, way } from "./words";

const VOLUME_ERROR = "Whole number, 1 to 2,147,483,647.";

/** "$4,560 a year" (whole dollars, as the board prints yearly figures). */
function perYear(v: number): string {
  return `${money(v, 0)} a year`;
}

export function ProgramsScreen() {
  const { user } = useAuth();
  const canEdit = canMutateWorkspace(user?.role);
  const pf = usePortfolio();
  const [toastNode, toast] = useToast();
  const [open, setOpen] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const [confirm, setConfirm] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [vols, setVols] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    if (!confirm) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setConfirm(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirm]);

  const data = pf.data;
  const rows = React.useMemo(() => [...(data?.rows ?? [])].sort((a, b) => a.filename.localeCompare(b.filename)), [data]);
  const programs = React.useMemo(() => (data ? declaredPrograms(data) : []), [data]);
  const current = open ?? (draft.trim() || null);
  const inOpen = data && open ? rowsInProgram(data, open) : [];
  const candidates = rows.filter((r) => !open || r.context?.program !== open);
  const nFree = rows.filter((r) => !r.context?.program).length;
  const nVol = rows.filter((r) => resolvedAnnualVolume(r) != null).length;
  const roll = open ? programs.find((p) => p.program === open) ?? null : null;

  const text = (r: PortfolioRow) => (vols[r.part_key] !== undefined ? vols[r.part_key] : r.context?.annual_volume != null ? String(r.context.annual_volume) : "");
  const setText = (k: string, v: string) => setVols((m) => ({ ...m, [k]: v }));
  const clearText = (k: string) =>
    setVols((m) => {
      const n = { ...m };
      delete n[k];
      return n;
    });

  const write = async (r: PortfolioRow, patch: { program?: string | null; annual_volume?: number | null }, ok: string) => {
    if (busy) return false;
    setBusy(r.part_key);
    setErr(null);
    try {
      const { delta } = await assignContext(r.part_key, patch);
      patchPortfolio(r.part_key, delta);
      clearText(r.part_key);
      toast(ok);
      return true;
    } catch (e) {
      setErr(`${r.filename}: ${errorText(e, "nothing changed.")}`);
      return false;
    } finally {
      setBusy(null);
    }
  };

  const savedText = (r: PortfolioRow, v: number | null) => (v == null ? "Yearly volume cleared" : `Saved · ${num(v)} a year${r.quantities.includes(v) ? "" : ` · not priced at ${num(v)}`}`);

  const commitVolume = (r: PortfolioRow) => {
    const raw = vols[r.part_key];
    if (raw === undefined) return;
    const v = parseAnnualVolume(raw);
    if (v === undefined) return;
    if (v === (r.context?.annual_volume ?? null)) {
      clearText(r.part_key);
      return;
    }
    void write(r, { annual_volume: v }, savedText(r, v));
  };

  const add = (r: PortfolioRow) => {
    if (!current || !canEdit) return;
    const v = parseAnnualVolume(text(r));
    if (v === undefined) return;
    const other = r.context?.program && r.context.program !== current ? r.context.program : null;
    const patch: { program: string; annual_volume?: number | null } = { program: current };
    if (v !== (r.context?.annual_volume ?? null)) patch.annual_volume = v;
    void write(r, patch, `${other ? "Moved to" : "Added to"} ${current}`).then((ok) => {
      if (ok) {
        setOpen(current);
        setDraft("");
        setConfirm(null);
      }
    });
  };

  const tabs = TABS.parts;

  return (
    <RecWorld label="Programs">
      <PageHead
        title="Programs"
        meta={
          data
            ? [
                <>
                  <b className="num">{programs.length}</b> {programs.length === 1 ? "program" : "programs"}
                </>,
                <>
                  <b className="num">{nFree}</b> {nFree === 1 ? "part" : "parts"} not in a program
                </>,
                <>
                  <b className="num">{nVol}</b> with yearly volume
                </>,
              ]
            : [pf.error ? "Programs didn't load" : "Loading programs"]
        }
        tabs={tabs}
        tabsLabel="Parts"
      />
      <Content full={!data}>
        {!data ? (
          <section className="panel">{pf.error ? <LoadFailed what="programs" detail={pf.error} onRetry={() => void pf.reload()} /> : <Skeleton rows={4} label="Loading programs" />}</section>
        ) : (
          <>
            <section className="panel" aria-label="Programs">
              <div className="ph">
                <h2>Programs</h2>
                <span className="num">{programs.length}</span>
              </div>
              {!programs.length ? (
                <div className="empty" style={{ padding: "14px 24px 10px" }}>
                  <b>No programs</b>
                  <span>A program groups parts with a yearly volume to cost a year.</span>
                </div>
              ) : (
                <div className="list">
                  {programs.map((p) => (
                    <button
                      key={p.program}
                      type="button"
                      className={cx("card2", p.program === open && "on")}
                      aria-pressed={p.program === open}
                      onClick={() => {
                        setOpen(p.program);
                        setConfirm(null);
                      }}
                    >
                      <span style={{ minWidth: 0 }}>
                        <b>{p.program}</b>
                        <small>
                          {plural(p.parts, "part")} · {p.exposed_parts ?? 0} counted
                        </small>
                      </span>
                      <span className="c num">{p.annualized_cost_usd != null ? perYear(p.annualized_cost_usd) : "Withheld"}</span>
                    </button>
                  ))}
                </div>
              )}
              {canEdit ? (
                <div className="newp">
                  <label className="field">
                    New program
                    <input
                      type="text"
                      placeholder="Program name"
                      maxLength={120}
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onFocus={() => draft.trim() && setOpen(null)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          setOpen(null);
                        }
                      }}
                    />
                  </label>
                </div>
              ) : null}
            </section>
            <section className="panel" aria-label="Parts and programs">
              <div className="ph">
                <h2>Parts</h2>
                <span>
                  <Link href={R.parts}>Show in Parts</Link>
                </span>
              </div>
              {rows.length ? (
                <div className="list">
                  {rows.map((r) => {
                    const v = resolvedAnnualVolume(r);
                    return (
                      <div className="pr" key={r.part_key}>
                        <span className="th" aria-hidden="true">
                          <Glyph size={20} />
                        </span>
                        <span style={{ minWidth: 0 }}>
                          <b>{r.filename}</b>
                          <small>{r.context?.program ? `In ${r.context.program}` : "Not in a program"}</small>
                        </span>
                        <span className="c num">{v != null ? `${num(v)} a year${r.annual_volume_basis === "bom_rollup" ? " from BOM" : ""}` : "No yearly volume"}</span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <NoneYet
                  title="No priced parts"
                  actions={
                    <Link className="btn sm ink" href={R.check}>
                      Check a part
                    </Link>
                  }
                >
                  A part can join a program once it has a price.
                </NoneYet>
              )}
              {(data.summary?.excluded_no_cost_count ?? 0) > 0 ? (
                <p className="foot">{plural(data.summary.excluded_no_cost_count, "part")} without a price aren&apos;t listed.</p>
              ) : null}
            </section>
          </>
        )}
      </Content>
      {data ? (
        <RecSheet label="Program">
          <div className="top">
            <h2 className="stitle" style={{ overflowWrap: "anywhere" }}>
              {open ?? (draft.trim() || "New program")}
            </h2>
            <p className="smeta">
              {open ? `${plural(inOpen.length, "part")} · ${inOpen.filter((r) => resolvedAnnualVolume(r) != null).length} with yearly volume` : "Not saved"}
            </p>
            <div className="figs" aria-live="polite">
              <div className="fig">
                <span>Yearly cost</span>
                <b className={cx("num", open && roll?.annualized_cost_usd == null && "warn", open && roll?.annualized_cost_usd == null && "t")}>
                  {!open ? "—" : roll?.annualized_cost_usd != null ? money(roll.annualized_cost_usd, 0) : "Withheld"}
                </b>
                <small>
                  {!open
                    ? "Add parts with a yearly volume"
                    : (roll?.exposed_parts ?? 0) < inOpen.length
                      ? `${(roll?.exposed_parts ?? 0) ? "Partial: " : ""}${inOpen.length - (roll?.exposed_parts ?? 0)} not priced at its volume`
                      : "Engine pick × yearly volume"}
                </small>
              </div>
              <div className="fig">
                <span>Parts counted</span>
                <b className="num">{open ? roll?.exposed_parts ?? 0 : 0}</b>
                <small>of {open ? inOpen.length : 0} in the program</small>
              </div>
            </div>
          </div>
          <div className="scroll">
            {err ? (
              <p className="err2" role="alert">
                {err}
              </p>
            ) : null}
            {!open ? <p style={{ margin: "8px 12px 0", color: "var(--ink2)", fontSize: 13.5 }}>Saved when you add its first part.</p> : null}
            {open ? (
              <>
                <div className="gh">
                  <span>In this program</span>
                  <span className="num">{inOpen.length}</span>
                </div>
                <div>
                  {inOpen.map((r) => {
                    const t = text(r);
                    const v = parseAnnualVolume(t);
                    const bad = v === undefined;
                    const demand = resolvedAnnualVolume(r);
                    const bom = r.annual_volume_basis === "bom_rollup";
                    const basis = r.annualized_unit_cost;
                    const listId = `q-${r.part_key.slice(0, 12)}`;
                    const priceAt = demand != null && r.annualized_cost_usd == null ? demand : null;
                    return (
                      <div className="mp" key={r.part_key}>
                        <span className="th" aria-hidden="true">
                          <Glyph size={18} />
                        </span>
                        <span style={{ minWidth: 0 }}>
                          <b>{r.filename}</b>
                          <small>
                            {basis ? `${way(basis.process)} · ${money(basis.usd)} each at ${num(basis.qty)}` : demand != null ? `No price at ${num(demand)} a year` : "No yearly volume"}
                          </small>
                          {bom && demand != null ? (
                            <>
                              <small>
                                {num(demand)} a year from the {r.context?.parent_assembly ?? "assembly"} BOM
                              </small>
                              <span className="bom">The BOM is used first.</span>
                            </>
                          ) : null}
                          <span className={cx("yr", r.annualized_cost_usd == null && "w")}>{r.annualized_cost_usd != null ? perYear(r.annualized_cost_usd) : demand != null ? "Withheld" : ""}</span>
                          {bad ? (
                            <span className="err" role="alert" id={`${listId}-e`}>
                              {VOLUME_ERROR}
                            </span>
                          ) : null}
                          {canEdit ? (
                            <span className="acts2">
                              {priceAt != null ? (
                                <Link className="btn sm" href={`${R.part(r.part_key)}?qty=${priceAt}`}>
                                  Price at {num(priceAt)}
                                </Link>
                              ) : null}
                              {confirm !== `rm-${r.part_key}` ? (
                                <button type="button" className="btn sm ghost" onClick={() => setConfirm(`rm-${r.part_key}`)} disabled={!!busy}>
                                  Remove
                                </button>
                              ) : null}
                            </span>
                          ) : null}
                          {confirm === `rm-${r.part_key}` ? (
                            <Confirm
                              inline
                              label="Remove part"
                              question={`Remove from ${open}? Its yearly volume stays.`}
                              action="Remove"
                              onCancel={() => setConfirm(null)}
                              onConfirm={async () => {
                                const ok = await write(r, { program: null }, `${r.filename} removed from ${open}`);
                                if (ok) {
                                  setConfirm(null);
                                  // A program exists only while it has parts: the last removal leaves it as an unsaved draft.
                                  if (inOpen.length <= 1) {
                                    setDraft(open);
                                    setOpen(null);
                                  }
                                }
                              }}
                            />
                          ) : null}
                        </span>
                        <label className="vol">
                          {bom ? "Fallback per year" : "Per year"}
                          <input
                            type="text"
                            inputMode="numeric"
                            className={cx(bad && "bad")}
                            aria-label={`${bom ? "Fallback per year" : "Per year"} for ${r.filename}`}
                            aria-invalid={bad}
                            aria-describedby={bad ? `${listId}-e` : undefined}
                            list={listId}
                            placeholder={bom ? "Optional" : undefined}
                            value={t}
                            disabled={!canEdit || busy === r.part_key}
                            onChange={(e) => setText(r.part_key, e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                e.preventDefault();
                                commitVolume(r);
                              }
                            }}
                            onBlur={() => commitVolume(r)}
                          />
                          <datalist id={listId}>
                            {r.quantities.map((qq) => (
                              <option key={qq} value={qq} />
                            ))}
                          </datalist>
                          <small>Priced: {r.quantities.map(num).join(", ")}</small>
                        </label>
                      </div>
                    );
                  })}
                </div>
              </>
            ) : null}

            {canEdit ? (
              <>
                <div className="gh">
                  <span>Add parts</span>
                  <span className="num">{candidates.length}</span>
                </div>
                {!current ? <p style={{ margin: "0 12px 4px", color: "var(--warn)", fontSize: 12.5 }}>Name the program first.</p> : null}
                <div>
                  {candidates.map((r) => {
                    const t = text(r);
                    const v = parseAnnualVolume(t);
                    const bad = v === undefined;
                    const other = r.context?.program && r.context.program !== current ? r.context.program : null;
                    const blocked = !current || bad || !!busy;
                    const listId = `c-${r.part_key.slice(0, 12)}`;
                    const declared = r.context?.annual_volume ?? null;
                    return (
                      <div className="mp" key={r.part_key}>
                        <span className="th" aria-hidden="true">
                          <Glyph size={18} />
                        </span>
                        <span style={{ minWidth: 0 }}>
                          <b>{r.filename}</b>
                          <small>
                            {r.context?.program ? `In ${r.context.program} · ` : ""}
                            {declared != null ? `${num(declared)} a year declared` : r.annual_volume_basis === "bom_rollup" && resolvedAnnualVolume(r) != null ? `${num(resolvedAnnualVolume(r)!)} a year from BOM` : "No yearly volume"}
                          </small>
                          {bad ? (
                            <span className="err" role="alert" id={`${listId}-e`}>
                              {VOLUME_ERROR}
                            </span>
                          ) : null}
                          {confirm !== `mv-${r.part_key}` ? (
                            <span className="acts2">
                              <button
                                type="button"
                                className={cx("btn sm", blocked && "off")}
                                aria-disabled={blocked}
                                onClick={() => {
                                  if (blocked) return;
                                  if (other) setConfirm(`mv-${r.part_key}`);
                                  else add(r);
                                }}
                              >
                                {busy === r.part_key ? "Saving…" : other ? "Move here" : "Add"}
                              </button>
                            </span>
                          ) : (
                            <Confirm inline label="Move part" question={`Move out of ${other}?`} action="Move" onCancel={() => setConfirm(null)} onConfirm={() => add(r)} />
                          )}
                        </span>
                        <label className="vol">
                          Per year
                          <input
                            type="text"
                            inputMode="numeric"
                            className={cx(bad && "bad")}
                            placeholder="Optional"
                            aria-label={`Optional yearly volume for ${r.filename}`}
                            aria-invalid={bad}
                            aria-describedby={bad ? `${listId}-e` : undefined}
                            list={listId}
                            value={t}
                            onChange={(e) => setText(r.part_key, e.target.value)}
                          />
                          <datalist id={listId}>
                            {r.quantities.map((qq) => (
                              <option key={qq} value={qq} />
                            ))}
                          </datalist>
                        </label>
                      </div>
                    );
                  })}
                  {!candidates.length ? <p className="ro-note">Every priced part is in this program.</p> : null}
                </div>
              </>
            ) : (
              <p className="ro-note">Read only. Analysts and admins assign parts and set yearly volume.</p>
            )}
            {open ? (
              <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="btn sm"
                  onClick={() => {
                    setOpen(null);
                    setDraft("");
                    setConfirm(null);
                  }}
                >
                  All programs
                </button>
                <Link className="btn sm" href={R.parts}>
                  Show in Parts
                </Link>
              </div>
            ) : null}
          </div>
        </RecSheet>
      ) : null}
      {toastNode}
    </RecWorld>
  );
}
