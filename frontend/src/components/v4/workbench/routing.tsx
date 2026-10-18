"use client";

/**
 * F6 · Routing and DFM: the geometric route and why, every method's fit with
 * its first blocker, and the findings grouped into required fixes, advisory and
 * notes. Picking a finding (from the list or a method's blocker) lights its
 * faces on the part and pins it; ← → step through findings, Esc clears.
 */
import * as React from "react";
import { useSearchParams } from "next/navigation";
import { formatIssueValue } from "@/lib/inspection-bind";
import { groupPinpointIssues, pinpointLinkEvidence } from "@/lib/pinpoint-groups";
import { flattenIssues } from "@/lib/dfm-scope";
import { cx } from "../ui";
import { featureCells, findingRows, measureLine, methodMatrix, type FindingRow } from "./derive";
import { retryDfm, useWb } from "./session";
import { WbHead, useNeedFile, useToast } from "./chrome";
import { Turntable } from "./turntable";
import { baseMeta } from "./decision";
import { SEVERITY, methodName, money, qtyText } from "./words";
import type { TabProps } from "./workbench";

const FIT: Record<string, string> = {
  makeable_in_house: "clears floor checks",
  makeable_with_secondary_op: "clears with a second operation",
  makeable_not_on_owned: "doesn’t fit your machines",
  makeable_outsource_only: "outsource only",
  environment_excluded: "ruled out by the service conditions",
  not_makeable: "can’t make it as modeled",
  unknown: "not enough declared to say",
};

function words(id: string): string {
  const t = id.replace(/_/g, " ").trim();
  return t ? t[0].toUpperCase() + t.slice(1) : id;
}

function FindingList({ title, rows, sel, onPick }: { title: string; rows: FindingRow[]; sel: string | null; onPick: (k: string) => void }) {
  return (
    <>
      <div className="gh">
        <span>{title}</span>
        <span className="num">{rows.length}</span>
      </div>
      {rows.length ? (
        <div className="fis">
          {rows.map((r) => (
            <button key={r.key} type="button" className={cx("fi", r.key === sel && "on")} aria-pressed={r.key === sel} onClick={() => onPick(r.key)}>
              <i className={r.sev} aria-hidden="true" />
              <span>
                <b>{r.title}</b>
                <small>{r.sub}</small>
              </span>
              <span className={cx("loc", !r.localized && "no")}>{r.localized ? (r.key === sel ? "Shown" : "Locate") : "Whole part"}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="smeta" style={{ margin: "0 12px 6px" }}>
          None.
        </p>
      )}
    </>
  );
}

export function RoutingTab({ part, qty }: TabProps) {
  const s = useWb();
  const sp = useSearchParams();
  const toast = useToast();
  const { need, choose } = useNeedFile();
  const v = s.validation;
  const report = s.report;
  const findings = React.useMemo(() => findingRows(v), [v]);
  const matrix = React.useMemo(() => methodMatrix(v, report, qty, findings), [v, report, qty, findings]);
  const groups = React.useMemo(() => (v ? groupPinpointIssues(flattenIssues(v)) : []), [v]);
  const [evidence, setEvidence] = React.useState<string | null>(null);
  React.useEffect(() => {
    let live = true;
    setEvidence(null);
    if (v) void pinpointLinkEvidence(groups, v.analysis_mesh_hash).then((e) => live && setEvidence(e));
    return () => {
      live = false;
    };
  }, [v, groups]);

  const [picked, setPicked] = React.useState<{ v: unknown; key: string | null } | null>(null);
  const sel = picked && picked.v === v ? picked.key : (findings.find((f) => f.localized) ?? findings[0])?.key ?? null;
  const cur = findings.find((f) => f.key === sel) ?? null;
  const idx = cur ? findings.indexOf(cur) : -1;

  // An issue link (?issue=&issue_evidence=) opens its finding only against the same evidence.
  const linked = React.useRef<string | null>(null);
  React.useEffect(() => {
    const issue = sp.get("issue");
    if (!issue || !v || !evidence || linked.current === issue) return;
    linked.current = issue;
    const g = groups.find((x) => x.key === issue);
    const row = g ? findings.find((f) => g.members.some((m) => f.members.includes(m.key))) : null;
    if (row && sp.get("issue_evidence") === evidence) setPicked({ v, key: row.key });
    else toast("This issue link doesn’t match this part’s geometry and findings. Pick a finding to make a new link.");
  }, [sp, v, evidence, groups, findings, toast]);

  const select = React.useCallback(
    (key: string | null) => {
      setPicked({ v, key });
      const url = new URL(window.location.href);
      const row = key ? findings.find((f) => f.key === key) : null;
      const g = row ? groups.find((x) => x.members.some((m) => row.members.includes(m.key))) : null;
      if (g && evidence) {
        url.searchParams.set("issue", g.key);
        url.searchParams.set("issue_evidence", evidence);
      } else {
        url.searchParams.delete("issue");
        url.searchParams.delete("issue_evidence");
      }
      window.history.replaceState(window.history.state, "", url);
    },
    [v, groups, evidence, findings],
  );
  const go = (i: number) => {
    if (!findings.length) return;
    select(findings[(i + findings.length) % findings.length].key);
  };
  const onCardKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      go(idx - 1);
    } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      go(idx + 1);
    } else if (e.key === "Escape") {
      e.preventDefault();
      select(null);
    }
  };

  const geo = report?.geometry;
  const vg = v?.geometry;
  const bbox = geo?.bbox_mm ?? vg?.bounding_box_mm;
  const vol = geo ? geo.volume_cm3 : vg ? vg.volume_mm3 / 1000 : null;
  const faces = geo?.face_count ?? vg?.faces;
  const watertight = geo?.watertight ?? vg?.is_watertight;
  const routing = report?.routing ?? null;
  const geoPick = matrix.geoPick;
  const fit = geoPick ? report?.verification?.per_route?.[geoPick] ?? null : null;
  const errs = findings.filter((f) => f.sev === "error");
  const warns = findings.filter((f) => f.sev === "warning");
  const infos = findings.filter((f) => f.sev === "info");
  const cells = featureCells(v?.features);
  const dfmBusy = s.dfm.phase === "running";
  const filename = s.filename ?? report?.filename ?? v?.filename ?? "part";

  const meta = [
    ...baseMeta(s),
    matrix.total ? (
      <>
        <b>{matrix.total}</b> methods checked
      </>
    ) : (
      ""
    ),
    v ? (v.rule_pack ? `Rule pack ${v.rule_pack.name} ${v.rule_pack.version}` : "No rule pack") : "",
  ];

  return (
    <>
      <WbHead tab="routing" part={part} meta={meta} />
      <div className="wb-main fixh">
        <div className="wb-rtop">
          <div className="wb-rleft">
            <Turntable
              file={s.file}
              filename={s.filename}
              units={s.opts.units}
              analysisMeshHash={v?.analysis_mesh_hash ?? null}
              highlight={cur?.localized ? { faces: cur.faces, kind: cur.kind } : null}
              pin={cur?.localized ? { faces: cur.faces, region: cur.issue.region_center ?? null, kind: cur.kind } : null}
              label={`${filename}${cur ? `, showing ${cur.title}` : ""}.`}
              onChooseFile={choose}
            />
            {bbox ? (
              <p className="geo num">
                <span>
                  <b>{bbox.map((x) => (Math.abs(x) >= 10 ? Math.round(x) : Math.round(x * 10) / 10)).join(" × ")}</b> mm
                </span>
                {vol != null ? (
                  <span>
                    <b>{vol.toFixed(2)}</b> cm³
                  </span>
                ) : null}
                {faces != null ? (
                  <span>
                    <b>{faces.toLocaleString("en-US")}</b> faces
                  </span>
                ) : null}
                {watertight != null ? <span>{watertight ? "Watertight" : "Not watertight"}</span> : null}
              </p>
            ) : null}
            {cur ? (
              <div className="card5" role="region" aria-label="Selected finding" onKeyDown={onCardKey}>
                <div className="hd">
                  <span className={cx("sev", cur.sev)}>
                    {SEVERITY[cur.sev]} · {cur.issue.code}
                  </span>
                  <span className="nav num">
                    <button className="ib s" type="button" aria-label="Previous finding" onClick={() => go(idx - 1)}>
                      ‹
                    </button>
                    {idx + 1}/{findings.length}
                    <button className="ib s" type="button" aria-label="Next finding" onClick={() => go(idx + 1)}>
                      ›
                    </button>
                    <button className="ib s" type="button" aria-label="Clear selection" title="Clear selection (Escape)" onClick={() => select(null)}>
                      ✕
                    </button>
                  </span>
                </div>
                <b style={{ fontSize: 15, color: "var(--ink)", fontWeight: 600 }}>{cur.title}</b>
                <span>{cur.issue.message}</span>
                {cur.issue.fix_suggestion ? <span>{cur.issue.fix_suggestion}</span> : null}
                {cur.needs.length > 1 ? (
                  <span className="num">
                    Needs: {cur.needs.map((n) => `${methodName(n.process).toLowerCase()} ${formatIssueValue(n.issue, "required_value")}`).join(" · ")}
                  </span>
                ) : measureLine(cur.issue, formatIssueValue) ? (
                  <span className="num">{measureLine(cur.issue, formatIssueValue)}</span>
                ) : null}
                <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Applies to: {cur.processes.length ? cur.processes.map(methodName).join(", ") : "every method"}</span>
                <span style={{ color: "var(--ink3)", fontSize: 12 }}>
                  {cur.localized
                    ? s.file
                      ? (cur.issue.affected_face_count ?? 0) > cur.faces.length
                        ? `${cur.faces.length.toLocaleString("en-US")} of ${(cur.issue.affected_face_count ?? 0).toLocaleString("en-US")} faces marked on the part`
                        : "Shown on the part"
                      : "On the part once the file is chosen"
                    : "Whole part, no single area"}{" "}
                  · ← → step · Esc clears
                </span>
              </div>
            ) : findings.length ? (
              <p className="smeta" style={{ textAlign: "center" }}>
                Pick a finding to see it on the part.
              </p>
            ) : null}
          </div>
          <section className="panel mx" aria-labelledby="mx-h">
            <div className="ph">
              <h2 id="mx-h">All methods</h2>
              <span>Fit · first blocker{matrix.qty != null ? ` · each at ${qtyText(matrix.qty)}` : ""}</span>
            </div>
            {matrix.rows.length ? (
              <div className="mxl" role="list" aria-label="All methods">
                {matrix.rows.map((m) => (
                  <div key={m.process} className={cx("mr6", m.cls)} role="listitem">
                    <span className="nm">
                      <b>{m.name}</b>
                      <small>{m.note}</small>
                    </span>
                    <span>
                      <span className={cx("chip", m.chip)}>
                        <i />
                        {m.chipLabel}
                      </span>
                    </span>
                    <span className="scr num">{m.score}%</span>
                    <span className="c num">{m.cost != null ? money(m.cost) : "—"}</span>
                    {m.first ? (
                      <span style={{ gridColumn: "1 / -1", paddingBottom: 4 }}>
                        <button
                          type="button"
                          className="fb"
                          onClick={() => {
                            const f = m.first?.key ? findings.find((x) => x.key === m.first!.key) : null;
                            if (!f) {
                              toast("No single area for this blocker. It applies to the whole part.");
                              return;
                            }
                            select(f.key);
                            if (!f.localized) toast("No single area for this finding. Shown in the card.");
                          }}
                        >
                          {m.first.title} · locate
                        </button>
                      </span>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <p className="smeta" style={{ padding: "0 16px 14px" }}>
                {dfmBusy ? "Checking every method…" : "No method checks for this part yet."}
              </p>
            )}
            {matrix.foot ? <p className="mxf">{matrix.foot}</p> : null}
          </section>
        </div>
      </div>
      <aside className="sheet" aria-label="Routing and findings">
        <div className="top">
          <h2 className="stitle">{routing ? `Routes to ${methodName(routing.recommended_process)}` : v?.best_process ? `Best fit: ${methodName(v.best_process)}` : "No geometric route"}</h2>
          <p className="smeta">{routing ? `${words(routing.archetype)} · confidence ${routing.confidence.toFixed(1)}` : "The cost run gave no route for this part"}</p>
          <div className="figs" aria-live="polite">
            <div className="fig">
              <span>Can’t as drawn</span>
              <b className="num bad">{matrix.cantAsDrawn}</b>
              <small>of {matrix.total}</small>
            </div>
            <div className="fig">
              <span>Required fixes</span>
              <b className="num warn">{errs.length}</b>
            </div>
            <div className="fig">
              <span>Advisory</span>
              <b className="num">{warns.length}</b>
            </div>
            <div className="fig">
              <span>Notes</span>
              <b className="num">{infos.length}</b>
            </div>
          </div>
        </div>
        <div className="scroll">
          {s.dfm.phase === "error" || (dfmBusy && s.dfm.error) ? (
            <div className="errx" role="alert">
              <b>Detailed DFM didn’t load</b>
              <span>Cost results are unaffected. Try again re-runs the DFM check only.</span>
              {s.dfm.error ? <span className="fh">{s.dfm.error}</span> : null}
              <span>
                <button className="btn sm ink" type="button" disabled={dfmBusy} onClick={() => need("re-run the DFM check", () => retryDfm())}>
                  {dfmBusy ? "Checking…" : "Try again"}
                </button>
              </span>
            </div>
          ) : dfmBusy ? (
            <div className="note" role="status">
              <b>Checking DFM</b>
              <span>Every method is being checked against the part’s geometry.</span>
            </div>
          ) : null}
          <div className="gh">
            <span>Routing</span>
            <span>From your file</span>
          </div>
          {routing?.reasoning ? <p className="reason">{routing.reasoning}</p> : null}
          <div className="kv">
            {routing?.alternatives?.length ? (
              <>
                <span>Alternative</span>
                <b>{routing.alternatives.map(methodName).join(", ")}</b>
              </>
            ) : null}
            {typeof routing?.drivers?.nominal_wall_mm === "number" ? (
              <>
                <span>Nominal wall</span>
                <b className="num">{(routing.drivers.nominal_wall_mm as number).toFixed(1)} mm</b>
              </>
            ) : null}
            {typeof routing?.drivers?.rotational === "boolean" ? (
              <>
                <span>Round</span>
                <b>{routing.drivers.rotational ? "Yes" : "No"}</b>
              </>
            ) : null}
            {typeof routing?.drivers?.sheet_like === "boolean" ? (
              <>
                <span>Sheet-like</span>
                <b>{routing.drivers.sheet_like ? "Yes" : "No"}</b>
              </>
            ) : null}
            <span>Your machine</span>
            <b>
              {fit
                ? fit.best_machine && (fit.verdict === "makeable_in_house" || fit.verdict === "makeable_with_secondary_op")
                  ? `${fit.best_machine} · ${FIT[fit.verdict]}`
                  : words(FIT[fit.verdict] ?? fit.verdict)
                : report?.verification
                  ? "Not checked for this route"
                  : "Not checked · no machines declared"}
            </b>
            {fit ? (
              <>
                <span>Machines checked</span>
                <b className="num">{fit.machines_evaluated}</b>
              </>
            ) : null}
            {fit?.machine_rate_usd != null ? (
              <>
                <span>Machine rate</span>
                <b className="num">${+fit.machine_rate_usd.toFixed(2)}/h · yours</b>
              </>
            ) : null}
          </div>
          {v ? (
            <>
              <FindingList title="Required fixes" rows={errs} sel={sel} onPick={(k) => select(k === sel ? null : k)} />
              <FindingList title="Advisory" rows={warns} sel={sel} onPick={(k) => select(k === sel ? null : k)} />
              <FindingList title="Notes" rows={infos} sel={sel} onPick={(k) => select(k === sel ? null : k)} />
              {cells.length ? (
                <>
                  <div className="gh">
                    <span>Detected features</span>
                    <span className="num">{v.features?.length ?? 0}</span>
                  </div>
                  <div className="dc num">
                    {cells.map((c) => (
                      <div key={c.label}>
                        <b>{c.n}</b>
                        <span>{c.label}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : null}
            </>
          ) : !dfmBusy && s.dfm.phase !== "error" ? (
            <p className="smeta" style={{ margin: "8px 12px" }}>
              No saved DFM check for this part.
            </p>
          ) : null}
        </div>
      </aside>
    </>
  );
}
