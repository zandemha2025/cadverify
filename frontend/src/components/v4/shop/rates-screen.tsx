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
  useLaborRate,
  useOrg,
  usePartRecords,
  useRateCard,
} from "./common";
import {
  ShopApiError,
  createRateDraft,
  discardRateDraft,
  listChanges,
  proposeChange,
  updateRateDraft,
  type ChangeRequestRow,
  type RecordDetail,
} from "./shop-api";
import { longDate, procName, shortWhen, type RateVersionLike } from "./shop-derive";
import { SpecRates } from "./spec-rates";
import {
  PROV_TAG,
  countInputs,
  defaultsFrom,
  headlineEstimate,
  headlineQty,
  previewAt,
  regionsFromAssumptions,
  regionsFromPayload,
  rowsFromAssumptions,
  rowsFromPayload,
  applyDraft,
  draftFormFrom,
  type DraftForm,
} from "./rates-derive";

const money = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

type Shop = { id: string; name: string; region: string | null; source: string | null };

export function RatesScreen() {
  const rc = useRateCard();
  // One request per load: every part's newest record, the newest 12 with details.
  const recs = usePartRecords(12);
  const org = useOrg();
  const details: RecordDetail[] | null = recs.data?.details ?? null;
  const failed = 0;
  const labor = useLaborRate(rc, recs.data?.parts ?? null, details);
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

  const nParts = recs.data?.total_parts ?? 0;
  const governed = rc.view?.governed === true;
  const payload = rc.eff?.payload ?? null;
  const counts = React.useMemo(() => (details ? countInputs(details.map(headlineEstimate)) : null), [details]);

  // v0: the defaults the engine recorded on your newest checks.
  const v0defaults = React.useMemo(() => defaultsFrom((details ?? []).map((d) => d.result?.assumptions)), [details]);
  const v0src = details && v0defaults.length ? details[0] : null;
  const rows = governed ? rowsFromPayload(payload) : rowsFromAssumptions(v0defaults);
  const regions = governed ? regionsFromPayload(payload) : regionsFromAssumptions((details ?? []).map((d) => d.result?.assumptions));
  const versions = (rc.page?.versions ?? []) as RateVersionLike[];
  const waiting = (changes ?? []).filter((c) => c.status === "proposed" && c.asset_type === "rate_card");
  // The processes and materials your recent checks were priced with: the draft lists them first.
  const usedProcs = React.useMemo(() => Array.from(new Set((details ?? []).flatMap((d) => (d.result?.estimates ?? []).map((e) => e.process)))), [details]);
  const usedMaterials = React.useMemo(() => Array.from(new Set((details ?? []).flatMap((d) => (d.result?.estimates ?? []).map((e) => e.material)).filter(Boolean))), [details]);
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
                  As the engine recorded them on your newest checks, latest {shortWhen(v0src.created_at)}. Checks costed with a shop profile or your own override aren&apos;t counted.
                </p>
              ) : null}
            </div>
          ) : !governed && recs.data && recs.data.total_parts === 0 ? (
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
            inEffectName={inEffectName}
            waiting={waiting.length}
            usedProcs={usedProcs}
            usedMaterials={usedMaterials}
            onSent={() => {
              rc.reload();
              setNc((x) => x + 1);
            }}
          />
        </Panel>

        <SpecRates
          org={org}
          baseVersion={governed ? rc.view?.inEffect ?? null : null}
          inEffectName={inEffectName}
          onSent={() => {
            rc.reload();
            setNc((x) => x + 1);
          }}
        />

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
  inEffectName,
  waiting,
  usedProcs,
  usedMaterials,
  onSent,
}: {
  org: ReturnType<typeof useOrg>;
  drafting: boolean;
  setDrafting: (v: boolean) => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
  baseVersion: RateVersionLike | null;
  inEffectName: string;
  waiting: number;
  /** Processes and materials your recent checks were priced with: their rows come first. */
  usedProcs: string[];
  usedMaterials: string[];
  onSent: () => void;
}) {
  // A draft is a real new version from the card in effect: its own values prefill the form (ce-13).
  const [draft, setDraft] = React.useState<{ id: number; version: number; payload: Record<string, unknown> } | null>(null);
  const [form, setForm] = React.useState<DraftForm | null>(null);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [allProcs, setAllProcs] = React.useState(false);
  const [sent, setSent] = React.useState<{ version: number } | null>(null);
  const admin = isOrgAdmin(org);
  const ids = React.useId();

  React.useEffect(() => {
    if (!drafting || draft || busy || error) return;
    let live = true;
    setBusy(true);
    createRateDraft({ name: "Draft", change_note: "", from_version_id: baseVersion ? Number(baseVersion.id) : null }).then(
      (d) => {
        if (!live) {
          void discardRateDraft(d.id).catch(() => {});
          return;
        }
        const payload = (d.payload ?? {}) as Record<string, unknown>;
        setDraft({ id: d.id, version: d.version, payload });
        setForm(draftFormFrom(payload));
        setBusy(false);
        requestAnimationFrame(() => inputRef.current?.focus());
      },
      (e) => {
        if (!live) return;
        setBusy(false);
        setError(e instanceof ShopApiError && e.status === 403 ? "Only an organization admin can draft rates." : e instanceof Error ? e.message : "Couldn't start a draft.");
      },
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drafting]);

  // Leaving the page with a draft open discards it, as Cancel does.
  const open = React.useRef<number | null>(null);
  open.current = draft?.id ?? null;
  React.useEffect(() => () => {
    if (open.current != null) void discardRateDraft(open.current).catch(() => {});
  }, []);

  const close = async () => {
    const d = draft;
    setDraft(null);
    setForm(null);
    setErrors({});
    setError(null);
    setDrafting(false);
    if (d) await discardRateDraft(d.id).catch(() => {});
  };

  const send = async () => {
    if (!draft || !form) return;
    const r = applyDraft(draft.payload, form, procName);
    if (!r.ok) {
      setErrors(r.errors);
      return;
    }
    if (!r.changes.length) {
      setError(`Nothing changed from ${inEffectName}. Change a rate, then send it for review.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const note = r.changes.join("\n");
      await updateRateDraft(draft.id, { payload: r.payload, name: r.changes[0], change_note: r.changes.join("; ") });
      await proposeChange({ asset_type: "rate_card", target_version_id: draft.id, title: `Rate card v${draft.version}: ${r.changes.length === 1 ? r.changes[0].toLowerCase() : `${r.changes.length} changes`}`, note });
      setSent({ version: draft.version });
      open.current = null;
      setDraft(null);
      setForm(null);
      setDrafting(false);
      onSent();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send it for review.");
    } finally {
      setBusy(false);
    }
  };

  const set = (patch: Partial<DraftForm>, key?: string) => {
    setForm((f) => (f ? { ...f, ...patch } : f));
    setError(null);
    if (key) setErrors((e) => {
      if (!e[key]) return e;
      const n = { ...e };
      delete n[key];
      return n;
    });
  };
  const err = (k: string) => (errors[k] ? <span className="err" id={`${ids}-${k}`}>{errors[k]}</span> : null);
  const inv = (k: string) => (errors[k] ? { "aria-invalid": true as const, "aria-describedby": `${ids}-${k}` } : {});
  const procKeys = form ? Object.keys(form.machines) : [];
  const used = procKeys.filter((p) => usedProcs.includes(p));
  const shownProcs = allProcs || !used.length ? procKeys : used;

  if (sent && !drafting) {
    return (
      <div className="draft" aria-live="polite">
        <div className="toast" role="status" style={{ flex: 1, minWidth: 0 }}>
          <span>
            v{sent.version} sent for review. {inEffectName} stays in use until approved.
          </span>
          <Link href={R.changes} style={{ marginLeft: "auto" }}>
            View
          </Link>
        </div>
      </div>
    );
  }
  if (drafting && (admin || org == null)) {
    return (
      <div className="draft draftform" aria-live="polite">
        {!form ? (
          error ? (
            <span className="err" role="alert" style={{ flexBasis: "100%" }}>
              {error}
            </span>
          ) : (
            <span className="fh">Starting a draft from {inEffectName}…</span>
          )
        ) : (
          <>
            <div className="dgrid">
              <label className="field">
                Labor, $/h
                <input ref={inputRef} type="text" inputMode="decimal" aria-label="Labor rate ($/h)" value={form.labor} onChange={(e) => set({ labor: e.target.value }, "labor")} {...inv("labor")} />
                {err("labor")}
              </label>
              <label className="field">
                Overhead, %
                <input type="text" inputMode="decimal" aria-label="Overhead (percent)" value={form.overhead} onChange={(e) => set({ overhead: e.target.value }, "overhead")} {...inv("overhead")} />
                {err("overhead") ?? <small>On machine, labor and setup. 15 is 15%.</small>}
              </label>
              <label className="field">
                Margin, %
                <input type="text" inputMode="decimal" aria-label="Margin (percent)" value={form.margin} onChange={(e) => set({ margin: e.target.value }, "margin")} {...inv("margin")} />
                {err("margin") ?? <small>Markup on cost. 10 is 10%.</small>}
              </label>
            </div>
            <fieldset className="dset">
              <legend>Machine rates, $/h{used.length && !allProcs ? " · the processes your checks used" : ""}</legend>
              <div className="dgrid">
                {shownProcs.map((p) => (
                  <label className="field" key={p}>
                    {procName(p)}
                    <input type="text" inputMode="decimal" aria-label={`${procName(p)} machine rate ($/h)`} value={form.machines[p]} onChange={(e) => set({ machines: { ...form.machines, [p]: e.target.value } }, `machine:${p}`)} {...inv(`machine:${p}`)} />
                    {err(`machine:${p}`)}
                  </label>
                ))}
              </div>
              {used.length && used.length < procKeys.length ? (
                <button className="btn sm ghost" type="button" onClick={() => setAllProcs((a) => !a)}>
                  {allProcs ? "Only the processes your checks used" : `All ${procKeys.length} processes`}
                </button>
              ) : null}
            </fieldset>
            <fieldset className="dset">
              <legend>Material prices, $/kg · blank is the typical price</legend>
              <div className="dgrid">
                {form.materials.map((m, i) => (
                  <span className="field" key={i}>
                    <input type="text" aria-label={`Material ${i + 1} name`} placeholder="Material, as checks name it" value={m.name} list={`${ids}-mats`} onChange={(e) => set({ materials: form.materials.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) }, `material:${i}`)} {...inv(`material:${i}`)} />
                    <input type="text" inputMode="decimal" aria-label={`Material ${i + 1} price ($/kg)`} placeholder="$/kg" value={m.price} onChange={(e) => set({ materials: form.materials.map((x, j) => (j === i ? { ...x, price: e.target.value } : x)) }, `material:${i}`)} {...inv(`material:${i}`)} />
                    {err(`material:${i}`)}
                  </span>
                ))}
              </div>
              <datalist id={`${ids}-mats`}>
                {usedMaterials.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
              <button className="btn sm ghost" type="button" onClick={() => set({ materials: [...form.materials, { name: usedMaterials.find((m) => !form.materials.some((x) => x.name === m)) ?? "", price: "" }] })}>
                Add a material price
              </button>
            </fieldset>
            <div className="dact">
              <button className="btn ink sm" type="button" onClick={() => void send()} disabled={busy}>
                {busy ? "Sending…" : "Send for review"}
              </button>
              <button className="btn sm" type="button" onClick={() => void close()} disabled={busy}>
                Cancel
              </button>
              {error ? (
                <span className="err" role="alert">
                  {error}
                </span>
              ) : (
                <span className="fh">Draft v{draft?.version}, from {inEffectName}. Anything you don&apos;t change keeps its value.</span>
              )}
            </div>
          </>
        )}
      </div>
    );
  }
  return (
    <div className="draft" aria-live="polite">
      {admin || org == null ? (
        <>
          <button className="btn sm" type="button" onClick={() => setDrafting(true)} disabled={org == null}>
            Draft new version
          </button>
          <span className="fh">
            Labor, overhead, margin, machine rates and material prices. Used after review in Changes to review.
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
        .map((d) => {
          const a = (d.result?.assumptions ?? []).find((x) => x.name === "labor_rate");
          return { d, e: headlineEstimate(d), base: a?.value, card: a?.provenance === "DEFAULT" };
        })
        .filter((x): x is { d: RecordDetail; e: NonNullable<ReturnType<typeof headlineEstimate>>; base: number; card: boolean } => !!x.e && typeof x.base === "number")
        // Checks costed on the card first: a shop profile's labor rate isn't the card's.
        .sort((a, b) => Number(b.card) - Number(a.card)),
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
