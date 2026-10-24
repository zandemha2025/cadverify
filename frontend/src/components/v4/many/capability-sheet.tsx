"use client";

/**
 * Capability changes (board M2 sheet): which single change to your machines
 * would let the most blocked parts be made, from the stored per-part gaps.
 * Each card opens the parts to review. No machine prices exist in ScaleCAD.
 */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { Fig, Figs, Sheet } from "../ui";
import { Thumb, errorText } from "./common";
import { fetchUnlocked } from "./many-api";
import type { Machine, MakeRow } from "./makeability";
import { capCard, isoBox, type RankEntry } from "./tooling";

export interface Ranking {
  ranking: RankEntry[];
  summary: { acquisitions: number; parts_unlockable_by_one_acquisition: number; blocked_by_multiple_constraints: number; total_blocked: number; stale: boolean };
}

function Drawing({ e, machines }: { e: RankEntry; machines: Machine[] | null }) {
  const c = capCard(e, machines);
  const caps = c.machine?.capabilities;
  if (c.kind === "material" && c.machine && caps?.x && caps?.y && caps?.z) {
    const box = isoBox(caps.x, caps.y, caps.z);
    const dims = `${caps.x} × ${caps.y} × ${caps.z} mm`;
    return (
      <svg width="100%" height="128" viewBox="0 0 400 128" role="img" aria-label={`The ${c.machine.name} work area, ${dims}, to be qualified for ${c.materials.join(", ")}`}>
        <polygon points={box.floor} fill="#E3E7EC" />
        <path d={box.back} stroke="#AEB5BE" strokeDasharray="3 4" fill="none" />
        <path d={box.front} stroke="#5F656E" strokeWidth="1.5" fill="none" strokeLinejoin="round" />
        <text x="236" y="44" fontSize="12" fill="#3E434A">
          {c.machine.name}
        </text>
        <text x="236" y="62" fontSize="12" fill="#3E434A">
          {dims}
        </text>
        <text x="236" y="84" fontSize="12" fontWeight="600" fill="#5B3FC4">
          + {c.materials.join(", ")} stock
        </text>
      </svg>
    );
  }
  if (c.kind === "envelope" && c.bounds) {
    const max = Math.max(c.bounds.have, c.bounds.need) * 1.15;
    const w = (v: number) => Math.max(8, (v / max) * 300);
    const name = c.machine?.name ?? "Your machine";
    return (
      <svg width="100%" height="84" viewBox="0 0 400 84" role="img" aria-label={`${name} takes ${Math.round(c.bounds.have)} mm; the part needs at least ${Math.round(c.bounds.need)} mm`}>
        <text x="0" y="16" fontSize="12" fill="#3E434A">
          {name}
        </text>
        <rect x="0" y="22" width={w(c.bounds.have)} height="12" rx="3" fill="#9AA3AE" />
        <text x={w(c.bounds.have) + 7} y="32" fontSize="12" fontWeight="600" fill="#141414">
          {Math.round(c.bounds.have)} mm
        </text>
        <text x="0" y="56" fontSize="12" fill="#3E434A">
          This part needs at least
        </text>
        <rect x="0" y="62" width={w(c.bounds.need)} height="12" rx="3" fill="#8C5200" />
        <text x={w(c.bounds.need) + 7} y="72" fontSize="12" fontWeight="600" fill="#141414">
          {Math.round(c.bounds.need)} mm
        </text>
      </svg>
    );
  }
  return c.summary ? <p>{c.summary}</p> : null;
}

function Card({ e, i, machines, open, onToggle }: { e: RankEntry; i: number; machines: Machine[] | null; open: boolean; onToggle: () => void }) {
  const c = capCard(e, machines);
  const [rows, setRows] = React.useState<MakeRow[] | null>(null);
  const [cursor, setCursor] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const listId = React.useId();

  const load = React.useCallback(
    async (more: boolean) => {
      setBusy(true);
      try {
        const p = await fetchUnlocked(e.acquisition.process, e.acquisition.gate, more ? cursor : null);
        setRows((prev) => (more ? [...(prev ?? []), ...p.rows] : p.rows));
        setCursor(p.next_cursor);
        setErr(null);
      } catch (x) {
        setErr(errorText(x, "Parts didn’t load."));
      } finally {
        setBusy(false);
      }
    },
    [e.acquisition.process, e.acquisition.gate, cursor],
  );

  React.useEffect(() => {
    if (open && rows === null && !busy && !err) void load(false);
  }, [open, rows, busy, err, load]);

  return (
    <div className="inv">
      <div className="t">
        <i>{i + 1}</i>
        <b>{c.title}</b>
      </div>
      <Drawing e={e} machines={machines} />
      <button type="button" className="exp" aria-expanded={open} aria-controls={listId} onClick={onToggle}>
        Parts to review <span className="num">{e.parts_unlocked}</span> <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>
      <div id={listId} hidden={!open}>
        {open ? (
          err ? (
            <p role="alert" style={{ margin: 0, color: "var(--bad)", fontSize: 13 }}>
              {err}{" "}
              <button className="lk" type="button" onClick={() => void load(false)}>
                Try again
              </button>
            </p>
          ) : rows === null ? (
            <span role="status" style={{ color: "var(--ink3)", fontSize: 12.5 }}>
              Loading parts…
            </span>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {rows.map((r) => (
                <div className="unl" key={r.part_key}>
                  <Thumb name={r.filename} />
                  <span>
                    <b style={{ fontWeight: 600 }}>{r.filename ?? r.part_key.slice(0, 12)}</b>
                    {r.recommended_route?.material ? ` · ${r.recommended_route.material}` : ""}
                  </span>
                  <Link className="lk" href={R.part(r.part_key)} style={{ marginLeft: "auto" }} aria-label={`Open ${r.filename ?? "part"}`}>
                    Open
                  </Link>
                </div>
              ))}
              <span style={{ color: "var(--ink3)", fontSize: 12, display: "flex", gap: 8, alignItems: "center" }}>
                {cursor ? `${rows.length} of ${e.parts_unlocked} shown` : `All ${rows.length} shown`}
                {cursor ? (
                  <button className="lk" type="button" onClick={() => void load(true)} disabled={busy}>
                    {busy ? "Loading…" : "Load more"}
                  </button>
                ) : null}
              </span>
            </div>
          )
        ) : null}
      </div>
      {c.caveat ? <div className="cav">{c.caveat}</div> : null}
      <span className={e.stale ? "flag f-stale" : "flag f-fresh"} style={{ alignSelf: "flex-start" }}>
        {e.stale ? (e.stale_parts === e.parts_unlocked ? "Out of date" : `${e.stale_parts} out of date`) : "Up to date"}
      </span>
    </div>
  );
}

export function CapabilitySheet({ data, err, onRetry, machines }: { data: Ranking | null; err: string | null; onRetry: () => void; machines: Machine[] | null }) {
  const [open, setOpen] = React.useState<number | null>(0);
  const s = data?.summary;
  return (
    <Sheet label="What would make more parts in-house">
      <div className="top">
        <h2 className="stitle">Capability changes</h2>
        <p className="smeta">Ranked by parts unlocked</p>
        {s ? (
          <Figs>
            <Fig k="Blocked" v={String(s.total_blocked)} sub="parts" tone={s.total_blocked ? "warn" : undefined} />
            <Fig k="One change each" v={String(s.parts_unlockable_by_one_acquisition)} />
            <Fig k="Several changes" v={String(s.blocked_by_multiple_constraints)} />
          </Figs>
        ) : null}
      </div>
      <div className="scroll">
        {err ? (
          <div className="errx" role="alert" style={{ margin: "8px 12px" }}>
            <b>Capability changes didn’t load</b>
            <span>{err}</span>
            <span>
              <button className="btn sm ink" type="button" onClick={onRetry}>
                Try again
              </button>
            </span>
          </div>
        ) : !data ? (
          <div role="status" style={{ padding: "16px 12px", color: "var(--ink3)", fontSize: 13 }}>
            Loading capability changes…
          </div>
        ) : data.ranking.length === 0 ? (
          <div className="empty">
            <b>No single change unlocks a part</b>
            <span>
              {s && s.blocked_by_multiple_constraints > 0
                ? `${s.blocked_by_multiple_constraints} ${s.blocked_by_multiple_constraints === 1 ? "part needs" : "parts need"} several changes; check each against a proposed machine.`
                : "No part is blocked by one missing capability."}
            </span>
          </div>
        ) : (
          data.ranking.map((e, i) => (
            <Card key={`${e.acquisition.process}:${e.acquisition.gate ?? ""}`} e={e} i={i} machines={machines} open={open === i} onToggle={() => setOpen((k) => (k === i ? null : i))} />
          ))
        )}
        {s && s.blocked_by_multiple_constraints > 0 && data && data.ranking.length > 0 ? (
          <p style={{ margin: "8px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
            {s.blocked_by_multiple_constraints} more {s.blocked_by_multiple_constraints === 1 ? "part needs" : "parts need"} several changes and aren’t ranked here.
          </p>
        ) : null}
        <p style={{ margin: 12, color: "var(--ink3)", fontSize: 12.5 }}>No machine prices in ScaleCAD. Ranked by parts unlocked; check a proposed machine against each part.</p>
      </div>
    </Sheet>
  );
}
