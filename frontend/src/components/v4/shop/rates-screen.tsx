"use client";

/**
 * Rates (board S1): the rate card in effect (a governed, reviewed version or the
 * built-in default v0), its versions, regional multipliers, the bundled supplier
 * profiles, and on the right what the labor rate changes on one of your parts.
 * Drafting a new version sends it to Changes to review; nothing here edits a
 * card in place.
 */
import * as React from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api-base";
import { R, TABS } from "../routes";
import { Content, Empty, Loading, PageHead, Panel, Sheet, Src, cx } from "../ui";
import { useShell } from "../shell";
import {
  Banner,
  LaborFact,
  RateCardChip,
  ShopWorld,
  isOrgAdmin,
  recordDetail,
  useLaborRate,
  useOrg,
  useRateCard,
  useRecords,
} from "./common";
import {
  ShopApiError,
  createRateDraft,
  discardRateDraft,
  latestPerPart,
  listChanges,
  proposeChange,
  updateRateDraft,
  type ChangeRequestRow,
  type RecordDetail,
} from "./shop-api";
import { longDate, procName, shortWhen, type RateVersionLike } from "./shop-derive";
import {
  PROV_TAG,
  countInputs,
  headlineEstimate,
  headlineQty,
  previewAt,
  regionsFromAssumptions,
  regionsFromPayload,
  rowsFromAssumptions,
  rowsFromPayload,
} from "./rates-derive";

const DECIMAL = /^(?:\d+(?:\.\d*)?|\.\d+)$/;
const money = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

type Shop = { id: string; name: string; region: string | null; source: string | null };

/** The latest saved record per part, with details (cached for the session). */
function usePartDetails(records: ReturnType<typeof useRecords>["data"]): { details: RecordDetail[] | null; failed: number } {
  const [state, setState] = React.useState<{ details: RecordDetail[] | null; failed: number }>({ details: null, failed: 0 });
  React.useEffect(() => {
    if (!records) return;
    let live = true;
    const parts = latestPerPart(records).slice(0, 12);
    Promise.allSettled(parts.map((r) => recordDetail(r.id))).then((res) => {
      if (!live) return;
      const ok = res.filter((x): x is PromiseFulfilledResult<RecordDetail> => x.status === "fulfilled").map((x) => x.value);
      setState({ details: ok, failed: res.length - ok.length });
    });
    return () => {
      live = false;
    };
  }, [records]);
  return state;
}

export function RatesScreen() {
  const rc = useRateCard();
  const recs = useRecords();
  const org = useOrg();
  const { details, failed } = usePartDetails(recs.data);
  const labor = useLaborRate(rc, recs.data);
  const [drafting, setDrafting] = React.useState(false);
  const draftRef = React.useRef<HTMLInputElement>(null);
  const [changes, setChanges] = React.useState<ChangeRequestRow[] | null>(null);
  const [nc, setNc] = React.useState(0);

  React.useEffect(() => {
    let live = true;
    listChanges().then(
      (b) => live && setChanges(b.change_requests ?? []),
      () => live && setChanges(null)
    );
    return () => {
      live = false;
    };
  }, [nc]);

  const nParts = recs.data ? latestPerPart(recs.data).length : 0;
  const governed = rc.view?.governed === true;
  const payload = rc.eff?.payload ?? null;
  const counts = React.useMemo(() => (details ? countInputs(details.map(headlineEstimate)) : null), [details]);

  // v0: the defaults the engine recorded on your newest check that has them.
  const v0src = React.useMemo(() => (details ?? []).find((d) => rowsFromAssumptions(d.result?.assumptions).length > 0) ?? null, [details]);
  const rows = governed ? rowsFromPayload(payload) : rowsFromAssumptions(v0src?.result?.assumptions);
  const regions = governed ? regionsFromPayload(payload) : regionsFromAssumptions((details ?? []).map((d) => d.result?.assumptions));
  const versions = (rc.page?.versions ?? []) as RateVersionLike[];
  const waiting = (changes ?? []).filter((c) => c.status === "proposed" && c.asset_type === "rate_card");
  const matCount = governed && payload && typeof payload === "object" ? Object.keys(((payload as Record<string, unknown>).material_prices as object) ?? {}).length : 0;

  const startDraft = () => {
    setDrafting(true);
    requestAnimationFrame(() => draftRef.current?.focus());
  };

  const inEffectName = governed ? (rc.view?.inEffect?.version != null ? `v${rc.view.inEffect.version}` : "the published card") : "v0";

  return (
    <ShopWorld label="Rates">
      <PageHead
        title="Rates"
        meta={[
          <>
            Rate card <RateCardChip rc={rc} long action={{ label: "Draft new version", onClick: startDraft }} />
          </>,
          <LaborFact key="l" src={labor} />,
          ...(counts && counts.total === 0
            ? [<>No cost inputs yet</>]
            : [
                <>
                  <b className="num">{counts ? counts.yours : "…"}</b> of {counts ? counts.total : "…"} cost inputs yours
                </>,
                <>
                  <b className="num">{counts ? counts.measured : "…"}</b> measured
                </>,
              ]),
        ]}
        tabs={TABS.shop}
        tabsLabel="Your shop"
      />
      <Content>
        {rc.error ? (
          <Banner
            tone="bad"
            alert
            actions={
              <button className="btn sm" type="button" onClick={rc.reload}>
                Retry
              </button>
            }
          >
            <b>Couldn&apos;t read rates.</b> {rc.error}
          </Banner>
        ) : null}
        <Panel
          title={governed ? rc.view?.title ?? "Rate card" : "Default rates v0"}
          note={
            rc.view ? (
              <>
                <Src kind={governed ? "yours" : "typ"}>{governed ? "Reviewed" : "Typical"}</Src> in use
                {recs.data ? ` · ${nParts} ${nParts === 1 ? "part" : "parts"}` : ""}
              </>
            ) : null
          }
        >
          {!rc.view && !rc.error ? (
            <Loading rows={3} label="Reading the rate card" />
          ) : rows.length ? (
            <div style={{ padding: "0 16px 6px" }}>
              {rows.map((r) => (
                <div className="rk" key={r.key}>
                  <span>
                    {r.name}
                    {r.note ? <small>{r.note}</small> : null}
                  </span>
                  <b className="num">{r.value}</b>
                </div>
              ))}
              {!governed && v0src ? (
                <p className="fh" style={{ margin: "4px 0 6px" }}>
                  As the engine recorded them on {v0src.label || v0src.filename}, {shortWhen(v0src.created_at)}.
                </p>
              ) : null}
            </div>
          ) : !governed && recs.data && recs.data.length === 0 ? (
            <NotUsedYet />
          ) : !governed && (recs.error || (details && !v0src)) ? (
            <p className="fh" style={{ margin: "0 16px 8px" }}>
              {recs.error ? `Couldn't load your checks: ${recs.error}` : "Your saved checks don't record the default values."}
            </p>
          ) : governed ? (
            <p className="fh" style={{ margin: "0 16px 8px" }}>The card in effect doesn&apos;t list these values.</p>
          ) : (
            <Loading rows={3} label="Reading your checks" />
          )}
          <div className="kv" style={{ padding: "4px 16px 6px", borderTop: "1px solid rgba(20,24,31,.08)" }}>
            <span>Versions</span>
            <b>
              {rc.view ? (
                <>
                  <span className="num">{rc.view.authored}</span> authored · <span className="num">{rc.view.published}</span> published ·{" "}
                  <span className="num">{rc.view.drafts}</span> drafts
                </>
              ) : (
                "…"
              )}
            </b>
            <span>Reviewed rates</span>
            <b>{rc.view ? `${rc.view.flag ? "On" : "Off"}${org && org !== "none" ? ` for ${org.name}` : ""}` : "…"}</b>
            <span>Material price overrides</span>
            <b>{matCount ? `${matCount} material${matCount === 1 ? "" : "s"}` : "None"}</b>
          </div>
          <DraftControls
            org={org}
            drafting={drafting}
            setDrafting={setDrafting}
            inputRef={draftRef}
            baseVersion={governed ? rc.view?.inEffect ?? null : null}
            currentLabor={labor && labor !== "none" ? labor.value : null}
            inEffectName={inEffectName}
            waiting={waiting.length}
            onSent={() => {
              rc.reload();
              setNc((x) => x + 1);
            }}
          />
        </Panel>

        {versions.length ? (
          <Panel title="Versions" note={`${versions.length} authored`}>
            {versions.map((v) => {
              const live = rc.view?.inEffect?.id === v.id;
              const inReview = waiting.some((c) => c.target_version_id === v.id);
              return (
                <div className="vrow" key={String(v.id)}>
                  <span>
                    <b style={{ fontWeight: 600 }}>
                      v{v.version ?? "?"}
                      {v.name ? ` · ${v.name}` : ""}
                    </b>
                    <small>
                      Created {longDate(v.created_at)}
                      {v.published_at ? ` · published ${longDate(v.published_at)}` : ""}
                      {v.effective_from ? ` · in effect from ${longDate(v.effective_from)}` : ""}
                      {v.change_note ? ` · ${v.change_note}` : ""}
                    </small>
                  </span>
                  <span className={cx("chip", live ? "c-ok" : inReview ? "c-warn" : "c-unk")}>
                    <i aria-hidden="true" />
                    {live ? "In effect" : inReview ? "In review" : v.status === "published" ? "Published" : v.status === "archived" ? "Archived" : "Draft"}
                  </span>
                </div>
              );
            })}
            {waiting.length ? (
              <p className="fh" style={{ margin: "6px 16px 12px" }}>
                <Link href={R.changes}>Open Changes to review</Link>
              </p>
            ) : (
              <div style={{ height: 8 }} />
            )}
          </Panel>
        ) : null}

        <Panel title="Regional multipliers" note="× US value">
          {regions.length ? (
            <>
              <div className="rt num" role="table" aria-label="Regional multipliers">
                <span className="h" role="columnheader">
                  Region
                </span>
                <span className="h r" role="columnheader">
                  Labor
                </span>
                <span className="h r" role="columnheader">
                  Material
                </span>
                <span className="h r" role="columnheader">
                  Tooling
                </span>
                {regions.map((g) => (
                  <React.Fragment key={g.code}>
                    <span>{g.name}</span>
                    <span className="r">{g.labor}</span>
                    <span className="r">{g.material}</span>
                    <span className="r">{g.tooling}</span>
                  </React.Fragment>
                ))}
              </div>
              {!governed ? (
                <p className="fh" style={{ margin: "-4px 16px 12px" }}>
                  Regions your checks were costed in.
                </p>
              ) : null}
            </>
          ) : (
            <p className="fh" style={{ margin: "0 16px 12px" }}>{details ? "Shown after a check is costed." : "Reading your checks…"}</p>
          )}
        </Panel>

        <SupplierProfiles />
      </Content>
      <Sheet label="What the rates change" style={{ bottom: 20 }}>
        <RatePreview details={details} failed={failed} counts={counts} loadError={recs.error} capped={nParts > (details?.length ?? 0) && !failed} />
      </Sheet>
    </ShopWorld>
  );
}

function NotUsedYet() {
  const { pickFile } = useShell();
  return (
    <Empty
      title="Not used yet"
      actions={
        <button className="btn ink sm" type="button" onClick={pickFile}>
          Check a part
        </button>
      }
    >
      The default card&apos;s values show here after your first check.
    </Empty>
  );
}

function DraftControls({
  org,
  drafting,
  setDrafting,
  inputRef,
  baseVersion,
  currentLabor,
  inEffectName,
  waiting,
  onSent,
}: {
  org: ReturnType<typeof useOrg>;
  drafting: boolean;
  setDrafting: (v: boolean) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
  baseVersion: RateVersionLike | null;
  currentLabor: number | null;
  inEffectName: string;
  waiting: number;
  onSent: () => void;
}) {
  const [value, setValue] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [sent, setSent] = React.useState<{ version: number } | null>(null);
  const admin = isOrgAdmin(org);

  const send = async () => {
    const t = value.trim().replace(/^\$/, "").replace(/\s*\/\s*h$/i, "");
    if (!DECIMAL.test(t) || !(Number(t) > 0)) {
      setError("Enter the labor rate in dollars an hour, for example 42.");
      return;
    }
    const rate = Number(t);
    setBusy(true);
    setError(null);
    let draftId: number | null = null;
    try {
      const draft = await createRateDraft({
        name: `Labor $${rate}/h`,
        change_note: `Labor, loaded shop floor${currentLabor != null ? ` ${money(currentLabor)}/h →` : ""} ${money(rate)}/h`,
        from_version_id: baseVersion ? Number(baseVersion.id) : null,
      });
      draftId = draft.id;
      const pay = (draft.payload ?? {}) as Record<string, unknown>;
      const global = { ...((pay.global as Record<string, unknown>) ?? {}), labor_rate: rate };
      await updateRateDraft(draft.id, { payload: { ...pay, global } });
      await proposeChange({
        asset_type: "rate_card",
        target_version_id: draft.id,
        title: `Rate card v${draft.version}: labor ${money(rate)}/h`,
        note: `Labor, loaded shop floor${currentLabor != null ? ` ${money(currentLabor)}/h →` : ""} ${money(rate)}/h`,
      });
      setSent({ version: draft.version });
      setDrafting(false);
      setValue("");
      onSent();
    } catch (e) {
      if (draftId != null) await discardRateDraft(draftId).catch(() => {});
      const msg = e instanceof ShopApiError && e.status === 403 ? "Only an organization admin can draft rates." : e instanceof Error ? e.message : "Couldn't send it for review.";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="draft" aria-live="polite">
      {sent ? (
        <div className="toast" role="status" style={{ flex: 1, minWidth: 0 }}>
          <span>
            v{sent.version} sent for review. {inEffectName} stays in use until approved.
          </span>
          <Link href={R.changes} style={{ marginLeft: "auto" }}>
            View
          </Link>
        </div>
      ) : drafting && (admin || org == null) ? (
        <>
          <label className="field">
            Labor rate
            <input
              ref={inputRef}
              type="text"
              inputMode="decimal"
              aria-label="Labor rate ($/h)"
              placeholder="$/h"
              value={value}
              aria-invalid={error ? true : undefined}
              onChange={(e) => {
                setValue(e.target.value);
                setError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") void send();
                if (e.key === "Escape") setDrafting(false);
              }}
            />
          </label>
          <button className="btn ink sm" type="button" onClick={() => void send()} disabled={busy}>
            {busy ? "Sending…" : "Send for review"}
          </button>
          <button className="btn sm" type="button" onClick={() => setDrafting(false)} disabled={busy}>
            Cancel
          </button>
          {error ? (
            <span className="err" role="alert" style={{ flexBasis: "100%" }}>
              {error}
            </span>
          ) : (
            <span className="fh" style={{ flexBasis: "100%" }}>
              Every other value is copied from {inEffectName}.
            </span>
          )}
        </>
      ) : admin || org == null ? (
        <>
          <button className="btn sm" type="button" onClick={() => setDrafting(true)} disabled={org == null}>
            Draft new version
          </button>
          <span className="fh">
            Admins draft. Used after review in Changes to review.
            {waiting ? (
              <>
                {" "}
                <Link href={R.changes}>{waiting} waiting</Link>.
              </>
            ) : null}
          </span>
        </>
      ) : (
        <span className="fh">
          Admins draft new versions; they&apos;re used after review in <Link href={R.changes}>Changes to review</Link>.
        </span>
      )}
    </div>
  );
}

function SupplierProfiles() {
  const [shops, setShops] = React.useState<Shop[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    let live = true;
    fetch(`${API_BASE}/shops`, { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Request failed (${r.status})`);
        return r.json();
      })
      .then((b: { shops?: Shop[] }) => live && setShops(b.shops ?? []))
      .catch((e) => live && setError(e instanceof Error ? e.message : "Couldn't load."));
    return () => {
      live = false;
    };
  }, []);
  return (
    <Panel title="Supplier rate profiles" note={shops ? String(shops.length) : undefined}>
      {error ? (
        <p className="fh" style={{ margin: "0 16px 12px" }}>
          Couldn&apos;t load supplier profiles: {error}
        </p>
      ) : !shops ? (
        <Loading rows={2} label="Loading supplier profiles" />
      ) : shops.length === 0 ? (
        <p className="fh" style={{ margin: "0 16px 12px" }}>None.</p>
      ) : (
        <>
          {shops.map((s) => (
            <div className="shop" key={s.id}>
              <span>
                <b>{s.name}</b>
                <small>
                  {[s.region, s.source].filter(Boolean).join(" · ")}
                </small>
              </span>
              <span className="chip c-warn">
                <i aria-hidden="true" />
                Sample data
              </span>
            </div>
          ))}
          <div style={{ padding: "10px 16px 14px", borderTop: "1px solid rgba(20,24,31,.08)", color: "var(--ink2)", fontSize: 13 }}>
            Bundled examples, shown to every organization. Not your suppliers.
          </div>
        </>
      )}
    </Panel>
  );
}

function RatePreview({
  details,
  failed,
  counts,
  loadError,
  capped,
}: {
  details: RecordDetail[] | null;
  failed: number;
  counts: ReturnType<typeof countInputs> | null;
  loadError: string | null;
  capped: boolean;
}) {
  const usable = React.useMemo(
    () =>
      (details ?? [])
        .map((d) => ({ d, e: headlineEstimate(d), base: (d.result?.assumptions ?? []).find((a) => a.name === "labor_rate")?.value }))
        .filter((x): x is { d: RecordDetail; e: NonNullable<ReturnType<typeof headlineEstimate>>; base: number } => !!x.e && typeof x.base === "number"),
    [details]
  );
  // Prefer a part where labor moves the cost.
  const firstScaling = usable.findIndex((x) => previewAt(x.e, x.base, x.base).scaling > 0);
  const [pick, setPick] = React.useState<string | null>(null);
  const cur = usable.find((x) => x.d.id === pick) ?? usable[firstScaling >= 0 ? firstScaling : 0] ?? null;
  const [rate, setRate] = React.useState<number | null>(null);
  React.useEffect(() => setRate(null), [cur?.d.id]);

  if (loadError)
    return (
      <div className="top">
        <h2 className="stitle">What the rates change</h2>
        <p className="smeta">Couldn&apos;t load your checks: {loadError}</p>
      </div>
    );
  if (!details)
    return (
      <div className="top">
        <h2 className="stitle">What the rates change</h2>
        <p className="smeta" role="status">
          Reading your checks…
        </p>
      </div>
    );
  if (!cur)
    return (
      <div className="top">
        <h2 className="stitle">What the rates change</h2>
        <p className="smeta">{failed ? "Your checks didn't load." : "Shown on one of your parts after a check is costed."}</p>
      </div>
    );

  const base = cur.base;
  const r = rate ?? base;
  const assumptions = cur.d.result?.assumptions ?? [];
  const margin = assumptions.find((a) => a.name === "margin")?.value ?? 0;
  const overhead = assumptions.find((a) => a.name === "overhead")?.value ?? 0;
  const p = previewAt(cur.e, base, r, { margin, overhead });
  const laborLine = p.lines.find((l) => l.key === "labor_cost");
  const hours = laborLine?.name.match(/(\d+(?:\.\d+)?) h$/)?.[1];
  const presets = [base - 10, base, base + 10, base + 20, base + 30].filter((v) => v > 0);
  const qty = headlineQty(cur.d.quantities);
  const changed = Math.abs(p.delta) >= 0.005;
  const deltaText = !changed ? "$0.00" : `${p.delta > 0 ? "+" : "−"}${money(Math.abs(p.delta))}`;
  const c = counts;

  return (
    <>
      <div className="top">
        <h2 className="stitle">{cur.d.label || cur.d.filename}</h2>
        <p className="smeta">
          {procName(cur.e.process)} · {cur.e.material} · each at {qty}
        </p>
        <div className="figs" aria-live="polite">
          <div className="fig">
            <span>Cost each</span>
            <b className="num">{p.total != null ? money(p.total) : money(cur.e.unit_cost_usd)}</b>
            <small>{p.total != null ? `at $${r}/h labor` : "as recorded"}</small>
          </div>
          <div className="fig">
            <span>Finishing labor</span>
            <b className={cx("num", !laborLine && "t")}>{laborLine ? money(laborLine.value) : "None"}</b>
            {hours ? <small>{hours} h</small> : null}
          </div>
          <div className="fig">
            <span>Change</span>
            <b className="num">{deltaText}</b>
            <small>vs ${base}/h</small>
          </div>
        </div>
      </div>
      <div className="scroll">
        {usable.length > 1 ? (
          <div style={{ padding: "8px 12px 0" }}>
            <label className="field">
              Part
              <select aria-label="Part" value={cur.d.id} onChange={(e) => setPick(e.target.value)}>
                {usable.map((x) => (
                  <option key={x.d.id} value={x.d.id}>
                    {x.d.label || x.d.filename} · {procName(x.e.process)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}
        <div className="gh">
          <span>Labor rate</span>
          <span>Preview</span>
        </div>
        <div style={{ padding: "0 12px 4px" }}>
          <span className="seg" role="group" aria-label="Labor rate">
            {presets.map((v) => (
              <button key={v} type="button" className={cx("num", v === r && "on")} aria-pressed={v === r} onClick={() => setRate(v)}>
                ${v}
              </button>
            ))}
          </span>
        </div>
        <div className="lines" style={{ marginTop: 10 }}>
          {p.lines.map((l) => (
            <div className="ln" key={l.key}>
              <span>{l.name}</span>
              <span className={cx("src", l.scales && r !== base ? "s-typ" : `s-${l.prov}`)}>{l.scales && r !== base ? "Preview" : l.tag}</span>
              <b className="num">{money(l.value)}</b>
            </div>
          ))}
        </div>
        <p style={{ margin: "8px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
          Not saved. {p.scaling} of {p.lines.length} lines scale with the labor rate.
          {p.total == null ? " Margin, overhead or an order minimum apply, so cost each isn't re-run here." : ""}
        </p>
        <div className="gh" style={{ marginTop: 10 }}>
          <span>
            Cost inputs, {capped ? "newest " : ""}
            {c ? c.parts : "…"} {c?.parts === 1 ? "part" : "parts"}
          </span>
          <span className="num">{c ? c.total : ""}</span>
        </div>
        {c && c.total ? (
          <div
            className="post"
            role="img"
            aria-label={`${c.yours} of ${c.total} cost inputs are yours, ${c.file} from your file, ${c.typ} are typical, ${c.measured ? c.measured : "none"} measured`}
          >
            <i style={{ width: `${(c.yours / c.total) * 100}%`, background: "var(--yours)" }} />
            <i style={{ width: `${(c.file / c.total) * 100}%`, background: "var(--file)" }} />
            <i style={{ width: `${(c.typ / c.total) * 100}%`, background: "#C3C8CE" }} />
          </div>
        ) : null}
        <div className="kv">
          <span>{PROV_TAG.yours}</span>
          <b className="num">{c ? c.yours : "…"}</b>
          <span>From your file</span>
          <b className="num">{c ? c.file : "…"}</b>
          <span>{PROV_TAG.typ}</span>
          <b className="num">{c ? c.typ : "…"}</b>
          <span>Measured from real jobs</span>
          <b className="num">{c ? c.measured : "…"}</b>
        </div>
        <div style={{ padding: "8px 12px" }}>
          <Link className="btn sm" href={R.actuals}>
            Log a job
          </Link>
        </div>
      </div>
    </>
  );
}
