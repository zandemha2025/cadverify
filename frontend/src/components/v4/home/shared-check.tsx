/**
 * Shared check, view only (board P9): the file's manufacturability check, every
 * way best first, each a disclosure with its findings. No prices, machines or
 * records travel on this link.
 */
import * as React from "react";
import type { SharedAnalysis } from "@/lib/api";
import { Chip, Fig, Figs } from "../ui";
import { SharedFrame, SharedStage } from "./shared-frame";
import { checkFacts, checkWays, partFindings, type SharedCheckLite } from "./shared-derive";
import { longDate, sizeText, wayName } from "./words";
import { day } from "../datacontrol/words";

/** " · link ends 20 Nov 2026" when the sharer's link has an end date. */
export function linkEnds(data: unknown): string {
  const at = (data as { link_expires_at?: string | null } | null)?.link_expires_at;
  return at ? ` · link ends ${day(at)}` : "";
}

export function SharedCheck({ data }: { data: SharedAnalysis }) {
  const d = data as unknown as SharedCheckLite;
  const g = d.geometry ?? {};
  const faces = g.faces ?? d.face_count;
  const facts = [
    sizeText(g.bounding_box_mm),
    g.volume_mm3 != null ? `${(Math.round((g.volume_mm3 / 1000) * 100) / 100).toLocaleString("en-US")} cm³` : "",
    faces != null ? `${faces.toLocaleString("en-US")} faces` : "",
    g.is_watertight == null ? "" : g.is_watertight ? "watertight" : "not watertight",
  ]
    .filter(Boolean)
    .join(" · ");
  const ways = checkWays(d);
  const f = checkFacts(d);
  const whole = partFindings(d);
  return (
    <SharedFrame kind="Shared check">
      <main className="world" aria-label="Shared check">
        <SharedStage title={d.filename} facts={facts} foot="Checks from the file's shape; no material or machines given" />
        <aside className="sheet" aria-label="The check">
          <div className="top">
            <h2 className="stitle" style={{ overflowWrap: "anywhere" }}>
              {d.filename}
            </h2>
            <p className="smeta">Manufacturability check · {longDate(d.created_at)} · view only{linkEnds(data)}</p>
            <Figs>
              <Fig k="Highest design score" v={d.best_process ? wayName(d.best_process) : "None found"} />
              <Fig k="Can make it" v={`${f.can} of ${f.total}`} sub="processes, with checks" tone={f.can ? "ok" : undefined} />
              <Fig k="Can't as drawn" v={String(f.cant)} sub="processes" tone={f.cant ? "bad" : undefined} />
            </Figs>
          </div>
          <div className="scroll">
            {whole.length ? (
              <>
                <div className="gh">
                  <span>Whole part</span>
                  <span>{whole.length === 1 ? "1 finding" : `${whole.length} findings`}</span>
                </div>
                <ul style={{ margin: "0 12px 8px", padding: "8px 10px 8px 26px", borderRadius: 10, background: "rgba(20,24,31,.035)", fontSize: 13, color: "var(--ink2)" }}>
                  {whole.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </>
            ) : null}
            <div className="gh">
              <span>Every process, best first</span>
              <span>findings</span>
            </div>
            <div>
              {ways.map((w) =>
                w.findings.length ? (
                  <details className="h-wy" key={w.key}>
                    <summary aria-label={`${w.name}: ${w.verdict}, ${w.count}`}>
                      <span>{w.name}</span>
                      <small className="num">{w.count}</small>
                      <Chip tone={w.tone}>{w.verdict}</Chip>
                    </summary>
                    <ul>
                      {w.findings.map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </details>
                ) : (
                  <div className="h-wy none" key={w.key}>
                    <div className="h-sum">
                      <span>{w.name}</span>
                      <small className="num">{w.count}</small>
                      <Chip tone={w.tone}>{w.verdict}</Chip>
                      <span aria-hidden="true" />
                    </div>
                  </div>
                ),
              )}
            </div>
            <p style={{ margin: "10px 12px", color: "var(--ink3)", fontSize: 12.5 }}>Not shown: prices, machines, records.</p>
          </div>
        </aside>
      </main>
    </SharedFrame>
  );
}
