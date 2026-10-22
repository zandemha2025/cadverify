"use client";

/**
 * A catalog run's summary, laid out for paper: the buckets with their totals,
 * then every part under its bucket with its reason, machine time, material,
 * ownership and price. "Print or save as PDF" uses the browser's own print
 * dialog; the top bar and buttons don't print.
 */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { Empty, Loading } from "../ui";
import { errorText } from "./common";
import { fetchBoard } from "./catalog-api";
import { BUCKETS, OTHER, boardProgress, breakdownOf, bucketCount, capabilityGroups, hoursText, machineLine, massText, materialLine, materialWord, money, partLine, sortRows, type Board } from "./catalog-model";
import "./many.css";
import "./catalog.css";

function dateText(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function CatalogSummary({ batchId }: { batchId: string }) {
  const [board, setBoard] = React.useState<Board | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  React.useEffect(() => {
    let live = true;
    fetchBoard(batchId).then(
      (b) => live && setBoard(b),
      (e) => live && setErr(errorText(e, "The summary didn’t load.")),
    );
    return () => {
      live = false;
    };
  }, [batchId]);

  if (err) {
    return (
      <div className="cp">
        <Empty title="The summary didn’t load" actions={<Link className="btn sm" href={R.batch(batchId)}>Back to the run</Link>}>
          {err}
        </Empty>
      </div>
    );
  }
  if (!board) {
    return (
      <div className="cp">
        <Loading rows={6} label="Loading the summary" />
      </div>
    );
  }
  const total = board.rows.length;
  const prog = boardProgress(board);
  const machines = board.machines.map((m) => m.name).join(", ");
  return (
    <article className="cp" aria-label="Catalog run summary">
      <div className="cp-bar cp-noprint">
        <Link className="btn sm" href={R.batch(batchId)}>
          Back to the run
        </Link>
        <button className="btn sm ink" type="button" onClick={() => window.print()}>
          Print or save as PDF
        </button>
      </div>
      <h1>Catalog run</h1>
      <p className="pmeta">
        <span>{dateText(board.completed_at ?? board.created_at)}</span>
        <span>
          {total} {total === 1 ? "part" : "parts"}
        </span>
        <span>{board.machines.length ? `Against ${machines}` : "No machines declared"}</span>
        <span>{board.material_class ? materialWord(board.material_class) : "Material from the file or list"}</span>
        <span>{board.quantity.toLocaleString("en-US")} each unless listed</span>
        {prog.checking ? <span>{prog.checking} still checking</span> : null}
      </p>

      <h2>Sorted</h2>
      <div className="wide">
        <table>
          <thead>
            <tr>
              <th scope="col">Bucket</th>
              <th scope="col" className="r">
                Parts
              </th>
              <th scope="col" className="r">
                Machine time
              </th>
              <th scope="col" className="r">
                Material
              </th>
              <th scope="col" className="r">
                Price at quantity
              </th>
            </tr>
          </thead>
          <tbody>
            {[...BUCKETS, ...OTHER].map((d) => {
              const t = board.totals[d.key];
              if (!t?.parts && !BUCKETS.includes(d)) return null;
              return (
                <tr key={d.key}>
                  <td>
                    <span className="dot" style={{ background: d.color }} aria-hidden="true" />
                    {d.label}
                  </td>
                  <td className="r num">{t?.parts ?? 0}</td>
                  <td className="r num">{hoursText(t?.hours)}</td>
                  <td className="r num">{massText(t?.used_kg != null && t.used_parts ? t.used_kg : t?.mass_kg)}</td>
                  <td className="r num">{money(t?.cost_usd, 0)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {[...BUCKETS, ...OTHER].map((d) => {
        const rows = sortRows(board.rows.filter((r) => r.bucket === d.key), "hours");
        if (!rows.length) return null;
        const b = breakdownOf(board, d.key);
        const needs = d.key === "new_machine" ? capabilityGroups(rows) : [];
        return (
          <section key={d.key}>
            <h2>
              {d.label} · {bucketCount(board, d.key)}
            </h2>
            {b.machines.length || b.materials.length || needs.length ? (
              <p className="pmeta cp-res">
                {b.machines.map((m) => {
                  const l = machineLine(m);
                  return <span key={`m-${m.machine ?? ""}-${m.process ?? ""}`}>{`${l.label}: ${l.value}`}</span>;
                })}
                {b.materials.map((g) => {
                  const l = materialLine(g);
                  return <span key={`g-${g.material}`}>{`${l.label}: ${l.value}`}</span>;
                })}
                {needs.map((g) => (
                  <span key={`n-${g.key}`}>{`Needs ${g.text.charAt(0).toLowerCase()}${g.text.slice(1)}: ${g.rows.length} ${g.rows.length === 1 ? "part" : "parts"}`}</span>
                ))}
              </p>
            ) : null}
            <div className="wide">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Part</th>
                    <th scope="col">Why</th>
                    <th scope="col">Machine time</th>
                    <th scope="col">Material</th>
                    <th scope="col">Ownership</th>
                    <th scope="col" className="r">
                      Price
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const l = partLine(r);
                    return (
                      <tr key={r.item_id}>
                        <td>
                          {r.filename}
                          {r.part_number ? <small>{r.part_number}</small> : null}
                        </td>
                        <td>{r.reason ?? "—"}</td>
                        <td>{l.time}</td>
                        <td>{l.material}</td>
                        <td>{l.ownership}</td>
                        <td className="r">{l.price}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}

      {board.unmatched.length ? (
        <section>
          <h2>In the parts list, no file in the run · {board.parts_list?.unmatched ?? board.unmatched.length}</h2>
          <p className="foot" style={{ marginTop: 0 }}>
            {board.unmatched.map((u) => u.part_number ?? u.file).join(", ")}
          </p>
        </section>
      ) : null}

      <p className="foot">
        Each part was checked by ScaleCAD’s engine against the machines above: its shape measured, every route scored, and priced with this organization’s rates where it
        declared them, typical rates otherwise. Machine time and prices are model estimates, not quotes. Material is what each route uses (stock cut from, material printed with
        its supports), from the engine’s own estimate; a part’s own mass is its measured volume times the material’s book density. In-house prices use your machines’
        marginal rate (capital already spent). ScaleCAD has no machine prices, so a machine you’d need carries no purchase cost. Open the run in ScaleCAD for each number’s source.
      </p>
    </article>
  );
}
