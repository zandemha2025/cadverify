"use client";

/**
 * A catalog run's one-page answer, to print or save as PDF and forward: whose
 * run (the organization), its name and date, the answer (make N, buy M, the
 * rest, and the saving against what you pay today), then the parts by answer
 * with the parts list's part numbers and descriptions. Files the parts list
 * doesn't name are listed apart and left out of the answer. Every figure is the
 * board's; "Print or save as PDF" uses the browser's own print dialog, and the
 * buttons don't print.
 */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { Empty, Loading } from "../ui";
import { errorText } from "./common";
import { fetchBoard } from "./catalog-api";
import { runCounts, runCountsLine } from "./batch-model";
import { useUnits } from "../units/use-units";
import { inText } from "../units/units";
import {
  answerText,
  machinesText,
  money,
  procName,
  rowName,
  runTitle,
  runningRateLines,
  scopedRows,
  sortRows,
  unlistedRows,
  bucketDef,
  type Board,
  type BoardRow,
} from "./catalog-model";
import "./many.css";
import "./catalog.css";

function dateText(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
}

const qty = (n: number) => n.toLocaleString("en-US");

/** Part number and description first (what a plant manager knows the part by), the file under them. */
function Who({ r }: { r: BoardRow }) {
  const head = [r.part_number, r.description].filter(Boolean).join(" · ");
  return (
    <td>
      {head || rowName(r)}
      {head ? <small>{rowName(r)}</small> : null}
    </td>
  );
}

function priceSource(r: BoardRow): string {
  const b = r.buy;
  if (!b) return "";
  if (b.source === "you") return "your price";
  if (b.source === "parts_list") return "parts list";
  return b.process ? `${procName(b.process).toLowerCase()} outside, model` : "model";
}

export function CatalogSummary({ batchId }: { batchId: string }) {
  // Lengths in the engine's words read in the person's unit, as on the board.
  const { unit } = useUnits();
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
      <main className="cp">
        <Empty title="The summary didn’t load" actions={<Link className="btn sm" href={R.batch(batchId)}>Back to the run</Link>}>
          {err}
        </Empty>
      </main>
    );
  }
  if (!board) {
    return (
      <main className="cp">
        <Loading rows={6} label="Loading the summary" />
      </main>
    );
  }
  const rows = scopedRows(board);
  const apart = unlistedRows(board);
  const answer = answerText(board);
  const by = (k: string) => sortRows(rows.filter((r) => r.bucket === k), "cost");
  const make = by("in_house");
  const buy = by("outside");
  const newMachine = by("new_machine");
  const undecided = rows.filter((r) => ["cant_make", "not_checked", "not_sorted", "checking"].includes(r.bucket));
  const machines = board.machines.map((m) => (m.count && m.count > 1 ? `${m.count} × ${m.name}` : m.name)).join(", ");
  const saving = (r: BoardRow) => (r.saving ? money(r.saving.total, 0) : "—");
  return (
    <main className="cp" aria-label="Catalog run summary">
      <div className="cp-bar cp-noprint">
        <Link className="btn sm" href={R.batch(batchId)}>
          Back to the run
        </Link>
        <button className="btn sm ink" type="button" onClick={() => window.print()}>
          Print or save as PDF
        </button>
      </div>
      {board.org_name ? <p className="cp-org">{board.org_name}</p> : null}
      <h1>Make or buy: {runTitle(board)}</h1>
      <p className="pmeta">
        <span>{dateText(board.completed_at ?? board.created_at)}</span>
        <span>
          {qty(rows.length)} {rows.length === 1 ? "part" : "parts"}
          {board.has_list ? " on the parts list" : ""}
        </span>
        <span>{board.machines.length ? `${machinesText(board)}: ${machines}` : "No machines declared"}</span>
        <span>{board.has_list ? "Quantities a year from the parts list" : `${qty(board.quantity)} each`}</span>
        <span>{runCountsLine(runCounts(null, board))}</span>
      </p>

      {answer ? (
        <section className="cp-ans" aria-label="The answer">
          <h2>{answer.head}</h2>
          <p>{answer.sub}</p>
          {answer.missing ? <p className="miss">{answer.missing}</p> : null}
        </section>
      ) : null}

      {make.length ? (
        <section>
          <h2>Make in-house · {make.length}</h2>
          <div className="wide">
            <table>
              <thead>
                <tr>
                  <th scope="col">Part</th>
                  <th scope="col" className="r">
                    A year
                  </th>
                  <th scope="col">On</th>
                  <th scope="col" className="r">
                    Make, each
                  </th>
                  <th scope="col" className="r">
                    Buy, each
                  </th>
                  <th scope="col" className="r">
                    Saving a year
                  </th>
                </tr>
              </thead>
              <tbody>
                {make.map((r) => (
                  <tr key={r.item_id}>
                    <Who r={r} />
                    <td className="r num">{qty(r.quantity)}</td>
                    <td>
                      {r.route?.machine ?? procName(r.route?.process)}
                      <small>{r.material.name ?? ""}</small>
                    </td>
                    <td className="r num">{money(r.make?.unit_cost_usd ?? r.unit_cost_usd)}</td>
                    <td className="r num">
                      {r.buy ? money(r.buy.unit_cost_usd) : "—"}
                      {r.buy ? <small>{priceSource(r)}</small> : null}
                      {r.buy && r.make && r.buy.unit_cost_usd < r.make.unit_cost_usd ? <small>a tie: inside the make estimate’s range</small> : null}
                    </td>
                    <td className="r num">{saving(r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {buy.length ? (
        <section>
          <h2>Buy · {buy.length}</h2>
          <div className="wide">
            <table>
              <thead>
                <tr>
                  <th scope="col">Part</th>
                  <th scope="col" className="r">
                    A year
                  </th>
                  <th scope="col" className="r">
                    Buy, each
                  </th>
                  <th scope="col">Why</th>
                </tr>
              </thead>
              <tbody>
                {buy.map((r) => (
                  <tr key={r.item_id}>
                    <Who r={r} />
                    <td className="r num">{qty(r.quantity)}</td>
                    <td className="r num">
                      {money(r.buy?.unit_cost_usd ?? r.unit_cost_usd)}
                      <small>{priceSource(r) || (r.route?.process ? `${procName(r.route.process).toLowerCase()}, model` : "")}</small>
                    </td>
                    <td>{r.reason ? inText(r.reason, unit) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {newMachine.length || undecided.length ? (
        <section>
          <h2>Not decided here · {newMachine.length + undecided.length}</h2>
          <div className="wide">
            <table>
              <thead>
                <tr>
                  <th scope="col">Part</th>
                  <th scope="col">Answer</th>
                  <th scope="col">Why</th>
                </tr>
              </thead>
              <tbody>
                {[...newMachine, ...undecided].map((r) => (
                  <tr key={r.item_id}>
                    <Who r={r} />
                    <td>{bucketDef(r.bucket).label}</td>
                    <td>{r.reason ? inText(r.reason, unit) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {board.unmatched.length ? (
        <section>
          <h2>On the parts list, no file in the run · {board.parts_list?.unmatched ?? board.unmatched.length}</h2>
          <p className="cp-list">{board.unmatched.map((u) => [u.part_number, u.description].filter(Boolean).join(" · ") || u.file).join("; ")}</p>
        </section>
      ) : null}

      {apart.length ? (
        <section>
          <h2>In the ZIP, not on the parts list · {apart.length}</h2>
          <p className="cp-list">
            {apart.map((r) => `${rowName(r)} (${bucketDef(r.bucket).label.toLowerCase()})`).join("; ")}. At the run’s quantity and material, and not in the answer above.
          </p>
        </section>
      ) : null}

      <p className="foot">
        {board.bucket_rule ? `${board.bucket_rule} ` : ""}
        Make prices are ScaleCAD’s model estimates on your machines at their running rates (the hourly rate you set, less the share that pays for the machine
        itself); buy prices are yours where you gave one, else ScaleCAD’s model of an outside shop, not a quote. The saving is against what you pay today, at the
        listed quantity a year.
        {runningRateLines(board).length ? ` ${runningRateLines(board).join(". ")}.` : ""} Open the run in ScaleCAD for every number’s source.
      </p>
    </main>
  );
}
