"use client";

/**
 * The part page's line in the Cost view: your shop's actual for this part next
 * to ScaleCAD's estimate. "Your actual: 4.1 h, ScaleCAD 4.4 h (+7%)". With no
 * actual yet, one quiet line says where they come from.
 */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { getAccuracy, type Accuracy } from "./api";
import { contextLine, partLines } from "./words";
import "./validation.css";

export function PartActuals({ partKey }: { partKey: string }) {
  const [data, setData] = React.useState<Accuracy | null>(null);
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => {
    let live = true;
    setData(null);
    setFailed(false);
    getAccuracy({ part: partKey }).then(
      (d) => live && setData(d),
      () => live && setFailed(true)
    );
    return () => {
      live = false;
    };
  }, [partKey]);
  if (failed || !data) return null;
  const lines = partLines(data.rows);
  const notCompared = data.rows.filter((r) => !r.hours && !r.cost);
  if (!data.rows.length) {
    return (
      <p className="val-part" style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, alignItems: "baseline" }}>
        <span>No actual from your shop for this part yet.</span>
        <Link href={R.actuals}>Import actuals</Link>
      </p>
    );
  }
  const calibrated = data.rows.some((r) => r.calibrated_record);
  return (
    <section className="val-part" aria-label="Your actuals for this part">
      {lines.slice(0, 4).map((l, i) => (
        <div key={`${l.row.id}-${l.kind}-${i}`}>
          <span className="ln1">
            <b>{l.text}</b>
            {l.row.test ? <span className="chip c-unk">Test</span> : null}
          </span>
          <small>
            {l.kind === "hours" ? "Machine hours per part" : "Cost per part"} · {contextLine(l.row)}
            {l.range ? ` · ${l.range}` : ""}
          </small>
        </div>
      ))}
      {notCompared.map((r) => (
        <small key={r.id}>
          {contextLine(r)}: {r.note ?? "not comparable"}
        </small>
      ))}
      {calibrated ? <small>This record includes your calibration; the comparison uses ScaleCAD’s estimate from before it.</small> : null}
      <Link href={`${R.actuals}#accuracy`}>All your actuals</Link>
    </section>
  );
}
