"use client";

/**
 * One saved record in the right sheet (board P2): what it found at a quantity,
 * the outcome (route, four choices, note, withdraw), approval (approve with a
 * note, reopen), the public link, exports, its cost inputs with their sources,
 * and the evidence. Viewers see it read-only (board P8).
 */
import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/ui/auth-provider";
import { canMutateWorkspace } from "@/lib/role-capabilities";
import { R } from "../routes";
import { Chip, Src, cx } from "../ui";
import { approve, errorText, exportRecord, reopen, setOutcome, shareRecord, unshareRecord, useMembers, usePartContext, useRecord } from "./api";
import { Confirm, Glyph, NotFound, PublicLink, RecSheet, Skeleton } from "./common";
import {
  cheapestAt,
  costLines,
  defaultQty,
  inHouseAt,
  outcomeLocks,
  rangeOf,
  recordFacts,
  routeOptions,
  routeValue,
  whatLine,
} from "./facts";
import { OUTCOMES, staleText, conditionsTag, conditionsText, money, num, outcomeLabel, parts, stampUtc, way, wayLower, type OutcomeKey } from "./words";

const NOTE_MAX = 1000;


export function RecordSheet({ id, toast }: { id: string; toast: (m: string) => void }) {
  const { detail, error, notFound, loading, retry } = useRecord(id);
  if (!detail) {
    return (
      <RecSheet label="The selected record">
        {notFound ? (
          <NotFound title="Record not found" back={{ label: "Back to records", href: R.records }} onRetry={() => void retry()}>
            It was removed, or the link is wrong.
          </NotFound>
        ) : error ? (
          <div className="empty" role="alert">
            <b>Couldn&apos;t load this record</b>
            <span>{error}</span>
            <span style={{ display: "flex", gap: 8, marginTop: 6 }}>
              <button type="button" className="btn sm ink" onClick={() => void retry()}>
                Retry
              </button>
            </span>
          </div>
        ) : (
          <Skeleton rows={6} label={loading ? "Loading the record" : "Loading"} />
        )}
      </RecSheet>
    );
  }
  return <Loaded key={detail.id} detail={detail} toast={toast} />;
}

type Detail = NonNullable<ReturnType<typeof useRecord>["detail"]>;

function Loaded({ detail, toast }: { detail: Detail; toast: (m: string) => void }) {
  const { user } = useAuth();
  const canEdit = canMutateWorkspace(user?.role);
  const people = useMembers();
  const ctx = usePartContext(detail.mesh_hash);
  const r = detail.result;
  const f = recordFacts(r);
  const qs = f.quantities;
  const basis = detail.disposition_basis ?? null;
  const dec = (detail.user_disposition ?? null) as OutcomeKey | null;
  const savedNote = detail.disposition_note ?? "";
  const approved = detail.approval_status === "approved";

  const [q, setQ] = React.useState<number | null>(() => defaultQty(detail));
  const options = React.useMemo(() => routeOptions(r, q), [r, q]);
  const basisValue = basis && basis.quantity === q ? routeValue(basis.process, basis.material) : null;
  const [routePick, setRoutePick] = React.useState<string | null>(null);
  const routeVal = options.find((o) => o.value === routePick)?.value ?? (basisValue && options.some((o) => o.value === basisValue) ? basisValue : options[0]?.value ?? null);
  const route = options.find((o) => o.value === routeVal) ?? null;
  const hasMine = q != null && inHouseAt(r, q).length > 0;
  const locks = outcomeLocks(r, route, q, hasMine);

  const [note, setNote] = React.useState(savedNote);
  const [apNote, setApNote] = React.useState("");
  const [confirm, setConfirm] = React.useState<"withdraw" | "reopen" | null>(null);
  const [why, setWhy] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [showSrc, setShowSrc] = React.useState(false);
  React.useEffect(() => setNote(detail.disposition_note ?? ""), [detail.disposition_note]);
  const dirty = note.trim() !== savedNote.trim();
  React.useEffect(() => {
    if (!confirm) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setConfirm(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirm]);

  const selected = (k: OutcomeKey) => dec === k && !!basis && !!route && basis.quantity === q && basis.process === route.process && basis.material === route.material;

  const run = async (name: string, fn: () => Promise<unknown>, ok: string) => {
    if (busy) return;
    setBusy(name);
    setErr(null);
    try {
      await fn();
      toast(ok);
      return true;
    } catch (e) {
      setErr(errorText(e, "Nothing changed. Retry."));
      return false;
    } finally {
      setBusy(null);
    }
  };
  const reopened = (t: string) => (approved ? `${t}; approval reopened` : t);

  const pick = (k: OutcomeKey) => {
    const lock = locks[k];
    if (lock) {
      setWhy(lock);
      return;
    }
    setWhy(null);
    if (selected(k) || !route || q == null) return;
    void run(k, () => setOutcome(detail.id, { disposition: k, note, quantity: q, process: route.process, material: route.material }), reopened("Outcome saved"));
  };

  const saveNote = () => {
    if (!dec || !dirty) return;
    void run("note", () => setOutcome(detail.id, { disposition: dec, note }), reopened("Note saved"));
  };

  const est = route?.est ?? null;
  const lines = costLines(est);
  const yours = lines.filter((l) => l.src === "yours").length;
  const range = rangeOf(est);
  const ch = q != null ? cheapestAt(r, q) : null;
  const mine = q != null ? inHouseAt(r, q)[0] ?? null : null;
  const mineRange = rangeOf(mine?.est);
  const env = ctx?.service_environment ?? null;
  const tag = conditionsTag(env);
  const condSentence =
    f.envDeclared === true ? `${conditionsText(env) ?? "Conditions were declared when it was checked"}.` : f.envDeclared === false ? "No service conditions." : "Conditions not recorded.";

  const who = (uid: number | null | undefined) => (uid == null ? "Someone" : user?.id === uid ? "You" : people?.get(uid) ?? `User ${uid}`);

  return (
    <RecSheet label="The selected record">
      <div className="top">
        <h2 className="stitle" style={{ overflowWrap: "anywhere" }}>
          {detail.label || detail.filename}
        </h2>
        <p className="smeta">
          {whatLine(f, tag)} · {stampUtc(detail.created_at)}
        </p>
        <p className="idl" style={{ margin: "4px 0 0" }}>
          Record {detail.id}
          {detail.engine_version ? ` · engine ${detail.engine_version}` : ""}
        </p>
        <div className="figs" aria-live="polite">
          {mine && q != null ? (
            <>
              <Fig k={`In-house at ${num(q)}`} v={money(mine.usd)} tone="ok" s={`${mine.machine ?? "Your machine"} · ${mine.material}`} />
              <Fig k={`Cheapest at ${num(q)}`} v={ch ? money(ch.usd) : "—"} s={ch ? way(ch.process) : `Not priced at ${num(q)}`} />
              <Fig small k={`Range at ${num(q)}`} v={mineRange?.text ?? "—"} s={mineRange ? (mineRange.validated ? "In-house, from real costs" : "In-house, typical") : "No range"} />
            </>
          ) : (
            <>
              <Fig k="Machine verdict" v={f.verdictLabel} tone={f.verdictTone === "unk" ? undefined : f.verdictTone} s={f.bestMachine ?? (f.inventoryDeclared ? "Your machines" : "Before machines")} />
              <Fig k={q != null ? `Cheapest at ${num(q)}` : "Cheapest"} v={ch ? money(ch.usd) : "—"} s={ch ? way(ch.process) : q != null ? `Not priced at ${num(q)}` : "No priced quantity"} />
            </>
          )}
        </div>
      </div>
      <div className="scroll swap">
        <div className="hero2">
          <span className="big" aria-hidden="true">
            <Glyph size={40} />
          </span>
          <p>{condSentence}</p>
        </div>

        {err ? (
          <p className="err2" role="alert">
            Nothing changed: {err}
          </p>
        ) : null}

        {/* Outcome */}
        <div className="gh">
          <span>Outcome</span>
          <span>
            {dec ? `${outcomeLabel(dec)}${basis ? ` · ${wayLower(basis.process)} at ${num(basis.quantity)}` : ""}` : "None recorded"}
          </span>
        </div>
        {canEdit ? (
          <>
            <label className="row2">
              <span>Quantity</span>
              <select
                aria-label="Outcome quantity"
                value={q ?? ""}
                onChange={(e) => {
                  setQ(Number(e.target.value));
                  setRoutePick(null);
                  setWhy(null);
                }}
                disabled={!qs.length}
              >
                {qs.length ? qs.map((v) => <option key={v} value={v}>{parts(v)}</option>) : <option value="">No priced quantity</option>}
              </select>
            </label>
            <label className="row2">
              <span>Route</span>
              <select
                aria-label="Route the outcome is about"
                value={routeVal ?? "none"}
                onChange={(e) => {
                  setRoutePick(e.target.value);
                  setWhy(null);
                }}
              >
                {options.length ? options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>) : <option value="none">No price at this quantity</option>}
              </select>
            </label>
            <div className="seg4" role="radiogroup" aria-label="Outcome">
              {OUTCOMES.map((o) => {
                const on = selected(o.key);
                const lock = locks[o.key];
                return (
                  <button
                    key={o.key}
                    type="button"
                    role="radio"
                    className={cx("opt", on && "on", !!lock && "lock")}
                    aria-checked={on}
                    aria-disabled={!!lock || !!busy}
                    title={lock ?? undefined}
                    onClick={() => pick(o.key)}
                  >
                    <i aria-hidden="true" />
                    {busy === o.key ? "Saving…" : o.label}
                  </button>
                );
              })}
            </div>
            {why ? (
              <p className="why" role="status">
                {why}
              </p>
            ) : null}
            <label className="tx">
              Outcome note
              <textarea maxLength={NOTE_MAX} placeholder="Reason, owner, next review" value={note} onChange={(e) => setNote(e.target.value)} />
              <span className="cnt">
                <span>{!dec ? (note.length ? "Choose an outcome to save this note." : "") : dirty ? <b>Unsaved. Save before approving.</b> : savedNote ? "Saved" : ""}</span>
                <span className="num">
                  {note.length}/{NOTE_MAX}
                </span>
              </span>
            </label>
            <div className="bar2">
              <button type="button" className={cx("btn sm", dec && dirty && "ink")} disabled={!dec || !dirty || !!busy} onClick={saveNote}>
                {busy === "note" ? "Saving…" : "Save note"}
              </button>
              {dec && confirm !== "withdraw" ? (
                <button type="button" className="btn sm ghost" onClick={() => setConfirm("withdraw")} disabled={!!busy}>
                  Withdraw outcome
                </button>
              ) : null}
            </div>
            {confirm === "withdraw" ? (
              <Confirm
                label="Withdraw outcome"
                question={approved ? "Withdraw the outcome? Approval reopens." : "Withdraw the outcome?"}
                action="Withdraw"
                onCancel={() => setConfirm(null)}
                onConfirm={async () => {
                  const ok = await run("withdraw", () => setOutcome(detail.id, { disposition: null }), reopened("Outcome withdrawn"));
                  if (ok) setConfirm(null);
                }}
              />
            ) : null}
          </>
        ) : (
          <div style={{ padding: "6px 12px 0", display: "flex", flexDirection: "column", gap: 8 }}>
            <span className={cx("opt ro", dec && "on")} aria-label={dec ? `Recorded outcome: ${outcomeLabel(dec)}` : "No outcome recorded"}>
              <i aria-hidden="true" />
              {dec ? `${outcomeLabel(dec)}${basis ? ` · ${way(basis.process)} · at ${num(basis.quantity)}` : ""}` : "No outcome recorded"}
            </span>
            {savedNote ? <p style={{ margin: 0, fontSize: 13, color: "var(--ink2)", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{savedNote}</p> : null}
            <p className="ro-note" style={{ margin: 0 }}>
              Read only. Analysts and admins record outcomes, approve and share.
            </p>
          </div>
        )}

        {/* Approval */}
        <div className="gh">
          <span>Approval</span>
          <span />
        </div>
        {detail.is_stale ? (
          <div className="stale" role="note">
            <b>Out of date</b>
            <span>
              {staleText(detail.stale_reason)}
              {detail.stale_at ? ` · ${stampUtc(detail.stale_at)}` : ""}. Check the part again before relying on it.
            </span>
          </div>
        ) : null}
        <div className="sign">
          <Chip tone={approved ? "ok" : "unk"}>{approved ? "Approved" : "Not reviewed"}</Chip>
          <span>
            {approved
              ? `${who(detail.approved_by_user_id)} · ${stampUtc(detail.approved_at)}${detail.approval_note ? ` · “${detail.approval_note}”` : ""}`
              : "Analysts and admins approve."}
          </span>
          {canEdit ? (
            approved ? (
              confirm === "reopen" ? null : (
                <button className="btn sm" type="button" onClick={() => setConfirm("reopen")} disabled={!!busy}>
                  Reopen
                </button>
              )
            ) : (
              <button
                className={cx("btn sm", !dirty && "ink")}
                type="button"
                aria-disabled={dirty || !!busy}
                onClick={() => {
                  if (dirty || busy) return;
                  void run("approve", () => approve(detail.id, apNote), "Approved").then((ok) => ok && setApNote(""));
                }}
              >
                {busy === "approve" ? "Approving…" : "Approve"}
              </button>
            )
          ) : null}
        </div>
        {canEdit && !approved ? (
          <label className="tx" style={{ paddingTop: 2 }}>
            Approval note
            <textarea maxLength={NOTE_MAX} placeholder="Optional" value={apNote} onChange={(e) => setApNote(e.target.value)} />
          </label>
        ) : null}
        {canEdit && !approved && dirty ? <p className="why">Save or clear the outcome note first.</p> : null}
        {confirm === "reopen" ? (
          <Confirm
            label="Reopen approval"
            question="Reopen approval? The record goes back to Not reviewed."
            action="Reopen"
            onCancel={() => setConfirm(null)}
            onConfirm={async () => {
              const ok = await run("reopen", () => reopen(detail.id), "Approval reopened");
              if (ok) setConfirm(null);
            }}
          />
        ) : null}

        {/* Public link */}
        <PublicLink
          shareUrl={detail.is_public ? detail.share_url : null}
          canShare={canEdit}
          blurb="Anyone with the link sees prices and assumptions."
          onCreate={() => shareRecord(detail.id)}
          onTurnOff={() => unshareRecord(detail.id)}
          toast={toast}
        />

        {/* Export */}
        <div className="gh">
          <span>Export</span>
          <span />
        </div>
        <div className="acts">
          {(["pdf", "csv", "json"] as const).map((k) => (
            <button
              key={k}
              className="btn sm"
              type="button"
              disabled={!!busy}
              onClick={() => void run(k, () => exportRecord(detail.id, detail.filename, k).then((n) => n), k === "pdf" ? "PDF downloaded" : k === "csv" ? "CSV downloaded" : "JSON downloaded")}
            >
              {busy === k ? "Exporting…" : k === "pdf" ? "PDF" : k === "csv" ? "CSV of cost inputs" : "JSON"}
            </button>
          ))}
          {canEdit ? (
            <Link className="btn sm" href={`${R.packages}?pick=${encodeURIComponent(detail.id)}`}>
              Supplier package
            </Link>
          ) : null}
          <Link className="btn sm" href={`${R.compare}?a=${encodeURIComponent(detail.id)}`}>
            Compare
          </Link>
          <Link className="btn sm" href={R.actuals}>
            Log actual cost
          </Link>
          {detail.mesh_hash ? (
            <Link className="btn sm ink" href={R.part(detail.mesh_hash)}>
              Open part
            </Link>
          ) : null}
        </div>

        {/* Cost inputs */}
        <div className="gh">
          <span>{route && q != null ? `Cost inputs · ${way(route.process)} at ${num(q)}` : "Cost inputs"}</span>
          <span>{lines.length ? `${yours} of ${lines.length} yours` : ""}</span>
        </div>
        {est && lines.length ? (
          <div className="lines">
            {lines.map((l) => (
              <div className="dl" key={l.key}>
                <span>
                  {l.label}
                  {showSrc && l.source ? <small>{l.source}</small> : null}
                </span>
                <b className="num">{money(l.usd)}</b>
                <Src kind={l.src}>{l.srcLabel}</Src>
              </div>
            ))}
            <div className="dl tot">
              <span>Each, at {num(q ?? 0)}</span>
              <b className="num">{money(est.unit_cost_usd)}</b>
              <span />
            </div>
          </div>
        ) : null}
        {est && lines.length ? (
          <div style={{ padding: "4px 12px 0" }}>
            <button type="button" className="btn sm ghost" aria-expanded={showSrc} onClick={() => setShowSrc((v) => !v)}>
              {showSrc ? "Hide how each input was worked out" : "Show how each input was worked out"}
            </button>
          </div>
        ) : (
          <p className="ro-note">{q == null ? "This record has no priced quantity." : `No cost inputs at ${num(q)} on this route.`}</p>
        )}

        {/* Evidence */}
        <div className="gh">
          <span>Evidence</span>
          <span />
        </div>
        <div className="kv ev">
          <span>Conditions</span>
          <b>{f.envDeclared === true ? conditionsText(env) ?? "Declared when checked" : f.envDeclared === false ? "None declared when checked" : "Not recorded"}</b>
          <span>Material class</span>
          <b>{f.material}</b>
          {f.ruledOut.length ? (
            <>
              <span>Ruled out by conditions</span>
              <b>{f.ruledOut.join(", ")}</b>
            </>
          ) : null}
          <span>Your machines</span>
          <b>{f.inventoryDeclared ? (f.bestMachine ? `Checked · fits the ${f.bestMachine}` : "Checked · none fits") : "None declared when checked"}</b>
          <span>Quantities priced</span>
          <b className="num">{qs.length ? qs.map(num).join(", ") : "None"}</b>
          {range && q != null ? (
            <>
              <span>Range at {num(q)}</span>
              <b className="num">
                {range.text}
                {range.pct != null ? ` · ±${range.pct}%` : ""}, {range.validated ? `from ${range.n} real costs` : "no real costs yet"}
              </b>
            </>
          ) : null}
          <span>File</span>
          <b style={{ overflowWrap: "anywhere" }}>
            {detail.filename}
            {detail.mesh_hash ? ` · SHA-256 ${detail.mesh_hash.slice(0, 12)}…` : ""}
          </b>
        </div>
      </div>
    </RecSheet>
  );
}

function Fig({ k, v, s, tone, small }: { k: string; v: string; s?: string; tone?: "ok" | "warn" | "bad"; small?: boolean }) {
  const isText = small || !/^[$\d−-]/.test(v);
  return (
    <div className="fig">
      <span>{k}</span>
      <b className={cx("num", tone, isText && "t")}>{v}</b>
      {s ? <small>{s}</small> : null}
    </div>
  );
}
