"use client";

/**
 * One analysis in the right sheet (board P4): time, faces, the best fit for the
 * shape, size and volume, every way with its findings (each opens to its
 * issues), whole-part findings and the mesh repair (a repaired copy with its
 * before and after), features, the records of this part, the public link, PDF
 * and Open part.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/ui/auth-provider";
import { canMutateWorkspace } from "@/lib/role-capabilities";
import RepairComparison from "@/components/RepairComparison";
import type { Issue, ProcessScore, RepairResult, ValidationResult } from "@/lib/api";
import { R } from "../routes";
import { setPendingFile } from "../pending-file";
import { Chip, cx } from "../ui";
import { analysisPdf, errorText, repairFile, repairedFile, saveBlob, shareAnalysis, unshareAnalysis, useAnalysis, usePartKeyForAnalysis, useRecordList } from "./api";
import { Dialog, Glyph, NotFound, PublicLink, RecSheet, Skeleton } from "./common";
import { summaryLines } from "./facts";
import { REPAIRABLE, finding, num, plural, rowTime, seconds, short, sizeText, stampUtc, volumeText, way, wayLower, type Tone } from "./words";
import { familyOf } from "../fix/problems";

export function AnalysisSheet({ id, toast }: { id: string; toast: (m: string) => void }) {
  const { detail, error, notFound, loading, retry } = useAnalysis(id);
  if (!detail) {
    return (
      <RecSheet label="The selected analysis">
        {notFound ? (
          <NotFound title="Analysis not found" back={{ label: "Back to analyses", href: R.analyses }} onRetry={() => void retry()}>
            It was removed, or the link is wrong.
          </NotFound>
        ) : error ? (
          <div className="empty" role="alert">
            <b>Couldn&apos;t load analyses</b>
            <span>{error}</span>
            <span style={{ display: "flex", gap: 8, marginTop: 6 }}>
              <button type="button" className="btn sm ink" onClick={() => void retry()}>
                Retry
              </button>
            </span>
          </div>
        ) : (
          <Skeleton rows={6} label={loading ? "Loading the analysis" : "Loading"} />
        )}
      </RecSheet>
    );
  }
  return <Loaded key={detail.id} detail={detail} toast={toast} />;
}

type Detail = NonNullable<ReturnType<typeof useAnalysis>["detail"]>;

/** A way's verdict in the board's words. */
export function wayVerdict(p: Pick<ProcessScore, "verdict" | "issues">): { label: string; tone: Tone } {
  if (p.verdict === "fail") return { label: "Can’t", tone: "bad" };
  if (p.verdict === "pass" && !p.issues.some((i) => i.severity !== "info")) return { label: "Can", tone: "ok" };
  return { label: "Check", tone: "warn" };
}

/** Ways that can make it as drawn first (best score first), then the ones that can't. */
export function sortWays(ps: ProcessScore[]): ProcessScore[] {
  return [...ps].sort((a, b) => Number(a.verdict === "fail") - Number(b.verdict === "fail") || b.score - a.score || a.process.localeCompare(b.process));
}

function Loaded({ detail, toast }: { detail: Detail; toast: (m: string) => void }) {
  const router = useRouter();
  const { user } = useAuth();
  const canEdit = canMutateWorkspace(user?.role);
  const r = detail.result;
  const ways = sortWays(r?.process_scores ?? []);
  const can = ways.filter((p) => p.verdict !== "fail").length;
  const [allWays, setAllWays] = React.useState(false);
  const [open, setOpen] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [repair, setRepair] = React.useState<RepairResult | null>(null);
  const [repairErr, setRepairErr] = React.useState<string | null>(null);
  const [compare, setCompare] = React.useState(false);
  const links = detail.decision_links ?? [];
  const partKey = usePartKeyForAnalysis(detail.id, links.map((l) => l.id));
  const list = useRecordList();

  const whole = r?.universal_issues ?? [];
  const meshIssues = whole.filter((i) => REPAIRABLE.has(i.code));
  const otherWhole = whole.filter((i) => !REPAIRABLE.has(i.code));
  const feats = React.useMemo(() => {
    const m = new Map<string, number>();
    for (const f of r?.features ?? []) m.set(f.kind, (m.get(f.kind) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [r]);
  const best = r?.best_process ?? null;
  const ms = detail.duration_ms ?? detail.analysis_time_ms ?? r?.analysis_time_ms ?? null;
  const g = r?.geometry;

  const pdf = async () => {
    if (busy) return;
    setBusy("pdf");
    setErr(null);
    try {
      await analysisPdf(detail.id, detail.filename);
      toast("PDF downloaded");
    } catch (e) {
      setErr(errorText(e, "The PDF didn't download."));
    } finally {
      setBusy(null);
    }
  };

  const runRepair = async (file: File) => {
    setBusy("repair");
    setRepairErr(null);
    try {
      setRepair(await repairFile(file));
    } catch (e) {
      setRepairErr(errorText(e, "The repair didn't run."));
    } finally {
      setBusy(null);
    }
  };

  const repairedCopy = repair ? repairedFile(repair, detail.filename) : null;
  const shown = allWays ? ways : ways.slice(0, 3);

  return (
    <RecSheet label="The selected analysis">
      <div className="top">
        <h2 className="stitle" style={{ overflowWrap: "anywhere" }}>
          {detail.filename}
        </h2>
        <p className="smeta">{stampUtc(detail.created_at)}</p>
        <p className="idl" style={{ margin: "4px 0 0" }}>
          Analysis {detail.id}
        </p>
        <div className="figs">
          <div className="fig">
            <span>Time</span>
            <b className="num">{seconds(ms)}</b>
            <small>{plural(ways.length, "process", "processes")} checked</small>
          </div>
          <div className="fig">
            <span>Faces</span>
            <b className="num">{num(g?.faces ?? detail.face_count)}</b>
            <small>{g ? (g.is_watertight ? "Watertight" : "Not watertight") : "—"}</small>
          </div>
          <div className="fig">
            <span>Best fit for the shape</span>
            <b className="t">{best ? way(best).replace(/ \(([^)]+)\)$/, "") : "None"}</b>
            <small>{best ? (/ \(([^)]+)\)$/.exec(way(best))?.[1] ?? "By shape") : "No process passes"}</small>
          </div>
        </div>
      </div>
      <div className="scroll swap">
        <div className="big2">
          <span className="big" aria-hidden="true">
            <Glyph size={52} />
          </span>
          <div className="kv">
            <span>Size</span>
            <b className="num">{sizeText(g?.bounding_box_mm)}</b>
            <span>Volume</span>
            <b className="num">{g ? volumeText(g.volume_mm3 / 1000) : "—"}</b>
            <span>Can make it</span>
            <b className="num">
              {can} of {ways.length} ways
            </b>
          </div>
        </div>
        {err ? (
          <p className="err2" role="alert">
            {err}
          </p>
        ) : null}

        {meshIssues.length ? (
          <>
            <div className="gh">
              <span>Mesh</span>
              <span>{repair?.repair_applied ? "Repaired copy" : plural(meshIssues.length, "issue")}</span>
            </div>
            <div className="fix" aria-live="polite">
              {!repair ? (
                <>
                  <b>{meshIssues[0].message}</b>
                  <span>A repair joins bodies and closes gaps in a copy. The saved check doesn&apos;t change.</span>
                  {canEdit ? (
                    <span className="r">
                      <label className={cx("btn sm ink fileb", busy === "repair" && "off")}>
                        {busy === "repair" ? "Repairing…" : "Choose file to repair"}
                        <input
                          type="file"
                          accept=".step,.stp,.stl,.iges,.igs"
                          aria-label="Choose the file you checked, to repair it"
                          disabled={busy === "repair"}
                          onChange={(e) => {
                            const f = e.target.files?.[0];
                            e.target.value = "";
                            if (f) void runRepair(f);
                          }}
                        />
                      </label>
                      <span className="pilot">No check used</span>
                      <span>Pick the same file you checked.</span>
                    </span>
                  ) : (
                    <span className="r">
                      <span>Analysts and admins can repair a copy.</span>
                    </span>
                  )}
                  {repairErr ? (
                    <span role="alert" style={{ color: "var(--bad)" }}>
                      {repairErr}
                    </span>
                  ) : null}
                </>
              ) : repair.repair_applied ? (
                <>
                  <b>Repaired copy ready</b>
                  <span>Check it again to replace these results.</span>
                  <BeforeAfter before={repair.original_analysis} after={repair.repaired_analysis} />
                  <span className="r">
                    {repairedCopy ? (
                      <button
                        type="button"
                        className="btn sm ink"
                        onClick={() => {
                          saveBlob(repairedCopy, repairedCopy.name);
                          toast(`Downloaded ${repairedCopy.name}`);
                        }}
                      >
                        Download repaired file
                      </button>
                    ) : null}
                    {repairedCopy ? (
                      <button
                        type="button"
                        className="btn sm"
                        onClick={() => {
                          setPendingFile(repairedCopy);
                          router.push(R.check);
                        }}
                      >
                        Check repaired file
                      </button>
                    ) : null}
                    <button type="button" className="btn sm ghost" onClick={() => setCompare(true)}>
                      Before and after
                    </button>
                  </span>
                </>
              ) : (
                <>
                  <b>Repair not possible</b>
                  <span>{repair.repair_details?.error ?? "The repair couldn't fix this mesh."}</span>
                  <span className="r">
                    <button type="button" className="btn sm" onClick={() => setRepair(null)}>
                      Try another file
                    </button>
                  </span>
                </>
              )}
            </div>
          </>
        ) : null}

        <div className="gh">
          <span>Processes</span>
          <span>
            {can} can · {ways.length - can} can’t as drawn
          </span>
        </div>
        <div className="ways">
          {shown.map((p) => {
            const v = wayVerdict(p);
            const isOpen = open === p.process;
            const first = p.issues.find((i) => i.severity === "error") ?? p.issues.find((i) => i.severity === "warning") ?? p.issues[0];
            return (
              <div key={p.process}>
                <button type="button" className="way" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : p.process)}>
                  <span style={{ minWidth: 0 }}>
                    {way(p.process)}
                    <small>{first ? finding(first.code) : "No findings"}</small>
                  </span>
                  <span className="n num">{plural(p.issues.length, "finding")}</span>
                  <Chip tone={v.tone}>{v.label}</Chip>
                </button>
                {partKey && v.tone === "bad" && first ? (
                  <Link className="waywhy" href={`${R.part(partKey)}?problem=${encodeURIComponent(familyOf(first.code).id)}&method=${encodeURIComponent(p.process)}`}>
                    Why it can’t, on the part ›
                  </Link>
                ) : null}
                {isOpen ? <Issues issues={p.issues} extra={p.recommended_material ? `Material checked: ${p.recommended_material}${p.recommended_machine ? ` · machine: ${p.recommended_machine}` : ""}` : null} /> : null}
              </div>
            );
          })}
        </div>
        {ways.length > 3 ? (
          <div style={{ padding: "6px 12px 0" }}>
            <button type="button" className="btn sm ghost" aria-expanded={allWays} onClick={() => setAllWays((x) => !x)}>
              {allWays ? "Show 3 processes" : `Show all ${ways.length} processes`}
            </button>
          </div>
        ) : null}

        {otherWhole.length ? (
          <>
            <div className="gh">
              <span>Whole part</span>
              <span>{plural(otherWhole.length, "finding")}</span>
            </div>
            <Issues issues={otherWhole} />
          </>
        ) : null}

        {feats.length ? (
          <>
            <div className="gh">
              <span>Features found</span>
              <span>{plural(r?.features?.length ?? 0, "feature")}</span>
            </div>
            <div className="kv ev">
              {feats.map(([k, n]) => (
                <React.Fragment key={k}>
                  <span>{k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())}</span>
                  <b className="num">{num(n)}</b>
                </React.Fragment>
              ))}
            </div>
          </>
        ) : null}

        <div className="gh">
          <span>Records of this part</span>
          <span className="num">{links.length}</span>
        </div>
        <div style={{ padding: "0 0 4px" }}>
          {links.length ? (
            links.map((x) => {
              const row = list.rows?.find((y) => y.id === x.id);
              return (
                <Link key={x.id} className="mr2" href={R.record(x.id)}>
                  <span style={{ minWidth: 0 }}>
                    {row ? summaryLines(row).what : x.make_now_process ? `ScaleCAD’s pick: ${wayLower(x.make_now_process)}` : "No process priced"} <small>· #{short(x.id)}</small>
                  </span>
                  <span className="t">{rowTime(x.created_at)} · Open</span>
                </Link>
              );
            })
          ) : (
            <p className="ro-note">No records yet. One is saved when the part is priced.</p>
          )}
        </div>

        <PublicLink
          shareUrl={detail.is_public ? detail.share_url : null}
          canShare={canEdit}
          blurb="Anyone with the link sees the checks, not your machines."
          onCreate={() => shareAnalysis(detail.id)}
          onTurnOff={() => unshareAnalysis(detail.id)}
          toast={toast}
        />

        <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap" }}>
          {partKey ? (
            <Link className="btn ink sm" href={R.part(partKey)}>
              Open part
            </Link>
          ) : null}
          <button className="btn sm" type="button" onClick={pdf} disabled={busy === "pdf"}>
            {busy === "pdf" ? "Generating PDF…" : "PDF"}
          </button>
        </div>
      </div>
      {compare && repair ? (
        <Dialog title="Before and after the repair" onClose={() => setCompare(false)}>
          <RepairComparison result={repair} originalFilename={detail.filename} />
        </Dialog>
      ) : null}
    </RecSheet>
  );
}

function Issues({ issues, extra }: { issues: Issue[]; extra?: string | null }) {
  return (
    <div className="issues">
      {issues.length ? (
        issues.map((i, n) => (
          <p key={`${i.code}-${n}`}>
            <b>{finding(i.code)}</b> {i.message}
            {i.fix_suggestion ? <small>Fix: {i.fix_suggestion}</small> : null}
            {i.citation?.standard ? (
              <small>
                Source: {i.citation.standard}
                {i.citation.clause ? ` ${i.citation.clause}` : ""}
              </small>
            ) : null}
          </p>
        ))
      ) : (
        <p>No findings for this way.</p>
      )}
      {extra ? <small>{extra}</small> : null}
    </div>
  );
}

function BeforeAfter({ before, after }: { before: ValidationResult; after: ValidationResult | null }) {
  const verdict = (v: string | undefined) => (v === "pass" ? "Clear" : v === "issues" ? "Advisory" : v === "fail" ? "Must change" : "Unknown");
  const canMake = (x: ValidationResult | null) => (x ? x.process_scores.filter((p) => p.verdict !== "fail").length : null);
  const rows: [string, string, string][] = [
    ["Verdict", verdict(before.overall_verdict), after ? verdict(after.overall_verdict) : "—"],
    ["Watertight", before.geometry.is_watertight ? "Yes" : "No", after ? (after.geometry.is_watertight ? "Yes" : "No") : "—"],
    ["Faces", num(before.geometry.faces), after ? num(after.geometry.faces) : "—"],
    ["Mesh issues", num(before.universal_issues.filter((i) => REPAIRABLE.has(i.code)).length), after ? num(after.universal_issues.filter((i) => REPAIRABLE.has(i.code)).length) : "—"],
    ["Processes that can make it", `${canMake(before)} of ${before.process_scores.length}`, after ? `${canMake(after)} of ${after.process_scores.length}` : "—"],
  ];
  return (
    <div className="ba" role="group" aria-label="Before and after the repair">
      <span />
      <b style={{ color: "var(--ink3)", fontWeight: 600 }}>Before</b>
      <b style={{ color: "var(--ink3)", fontWeight: 600 }}>After</b>
      {rows.map(([k, a, b]) => (
        <React.Fragment key={k}>
          <span>{k}</span>
          <b className="num">{a}</b>
          <b className="num">{b}</b>
        </React.Fragment>
      ))}
    </div>
  );
}
