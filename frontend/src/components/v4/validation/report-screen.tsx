"use client";

/**
 * The pilot report, laid out for paper: for one catalog run or every part, how
 * many parts, sorted into make in-house / buy outside / needs a new machine /
 * can't be made; the machine hours (by machine) and material (by grade) the
 * in-house parts need, and the machines you don't have; the
 * biggest wins; decisions recorded and who recorded them; and how close
 * ScaleCAD came to your actuals, with the caveats. Print from the browser, or
 * download the PDF the server renders from the same figures.
 */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { Empty, Loading } from "../ui";
import { getReport, reportPdfUrl, type Report } from "./api";
import { reportHref } from "./routes";
import { absPct, dateWord, factorWord, hoursWord, methodWord, moneyWord, pctWord, statsLine, summaryLine } from "./words";
import "./validation.css";
import { outOfDateText } from "../part/signoff";

function kg(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v < 100 ? `${v.toFixed(2)} kg` : `${Math.round(v).toLocaleString("en-US")} kg`;
}

function partial(n: number, of: number): string {
  return n && n !== of ? ` (${n} of ${of})` : "";
}

const OTHER_WORDS: Record<string, string> = { not_sorted: "checked without a machine verdict", not_checked: "couldn’t be checked", checking: "still checking" };

export function ReportScreen({ run }: { run: string | null }) {
  const [rep, setRep] = React.useState<Report | null>(null);
  const [err, setErr] = React.useState<{ msg: string; status: number } | null>(null);
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    setRep(null);
    setErr(null);
    getReport(run).then(
      (r) => live && setRep(r),
      (e) => live && setErr({ msg: e instanceof Error ? e.message : "The report didn’t load.", status: (e as { status?: number }).status ?? 0 })
    );
    return () => {
      live = false;
    };
  }, [run, n]);

  const back = run ? R.batch(run) : R.triage;
  if (err) {
    return (
      <div className="val-paper">
        <Empty
          title={err.status === 404 ? "This run isn’t available" : "The report didn’t load"}
          actions={
            <>
              <Link className="btn sm" href={back}>
                Back
              </Link>
              {err.status !== 404 ? (
                <button className="btn sm" type="button" onClick={() => setN((x) => x + 1)}>
                  Retry
                </button>
              ) : null}
            </>
          }
        >
          {err.msg}
        </Empty>
      </div>
    );
  }
  if (!rep) {
    return (
      <div className="val-paper">
        <Loading rows={6} label="Putting the report together" />
      </div>
    );
  }
  const a = rep.accuracy;
  const other = Object.entries(rep.other);
  return (
    <article className="val-paper val-rep" aria-label="Pilot report">
      <div className="val-bar val-noprint">
        <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <Link className="btn sm" href={back}>
            {run ? "Back to the run" : "Back to Make or buy"}
          </Link>
          {run ? (
            <Link className="btn sm ghost" href={reportHref(null)}>
              Every part instead
            </Link>
          ) : null}
        </span>
        <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <a className="btn sm" href={reportPdfUrl(run)} download>
            Download PDF
          </a>
          <button className="btn sm ink" type="button" onClick={() => window.print()}>
            Print
          </button>
        </span>
      </div>

      <h1>Pilot report</h1>
      <p className="pmeta">
        {rep.organization ? <span>{rep.organization}</span> : null}
        <span>{rep.scope.kind === "run" ? `Catalog run of ${dateWord(rep.scope.created_at ?? null)}${rep.scope.parts_list?.name ? `, parts list ${rep.scope.parts_list.name}` : ""}` : `Every part checked, at ${rep.scope.quantity} of each`}</span>
        <span>{dateWord(rep.generated_at)}</span>
      </p>

      {rep.headline ? (
        <div className="rlead">
          <b>{rep.headline.head}</b>
          {rep.headline.sub ? <span>{rep.headline.sub}</span> : null}
          {rep.headline.missing ? <small>{rep.headline.missing}</small> : null}
        </div>
      ) : null}
      {rep.coverage ? (
        <p className="rp">
          <b>{rep.coverage.text}.</b>
          {rep.coverage.not_checked ? ` Not checked: ${rep.coverage.reasons.map((g) => `${g.parts} ${g.reason.toLowerCase()}`).join(", ")}; they are listed at the end and aren’t in any figure here.` : ""}
        </p>
      ) : null}
      {rep.overloaded?.length ? (
        <p className="rp rover">Overloaded if every make part comes in-house: {rep.overloaded.join("; ")}.</p>
      ) : rep.in_house.machines.some((m) => m.available_hours) ? (
        <p className="rp">
          Every machine has the hours its make parts need:{" "}
          {rep.in_house.machines
            .filter((m) => m.available_hours)
            .map((m) => `${m.machine} ${hoursWord(m.hours)} of ${hoursWord(m.available_hours ?? null)} a year (${Math.round(m.utilization_pct ?? 0)}%)`)
            .join("; ")}
          .
        </p>
      ) : null}
      {rep.basis?.length ? (
        <>
          <p className="rp" style={{ marginBottom: 0 }}>
            <b>What the prices assume</b>
          </p>
          <ul className="cav">
            {rep.basis.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </>
      ) : null}

      <div className="rbk" role="group" aria-label="Parts by where they're made">
        <div>
          <span>Parts</span>
          <b className="num">{rep.parts}</b>
          <small>{rep.coverage?.not_checked ? `${rep.coverage.not_checked} not checked` : other.length ? `${other.reduce((s, [, v]) => s + v, 0)} not sorted` : "all sorted"}</small>
        </div>
        {rep.buckets.map((b) => (
          <div key={b.key}>
            <span>{b.label}</span>
            <b className="num">{b.parts}</b>
            <small>{b.hours ? `${hoursWord(b.hours)} machine time` : b.parts ? "no machine time" : "none"}</small>
          </div>
        ))}
      </div>

      <h2>Sorted</h2>
      <div className="val-wide">
        <table>
          <thead>
            <tr>
              <th scope="col">Where</th>
              <th scope="col" className="r">
                Parts
              </th>
              <th scope="col" className="r">
                Quantity
              </th>
              <th scope="col" className="r">
                Machine time
              </th>
              <th scope="col" className="r">
                Material
              </th>
              <th scope="col" className="r">
                Cost at quantity
              </th>
            </tr>
          </thead>
          <tbody>
            {rep.buckets.map((b) => (
              <tr key={b.key}>
                <td>{b.label}</td>
                <td className="r num">{b.parts}</td>
                <td className="r num">{(b.quantity ?? 0).toLocaleString("en-US")}</td>
                <td className="r num">
                  {hoursWord(b.hours)}
                  {partial(b.hours_parts, b.parts)}
                </td>
                <td className="r num">
                  {b.used_kg != null && b.used_parts ? kg(b.used_kg) : kg(b.mass_kg)}
                  {b.used_kg != null && b.used_parts ? partial(b.used_parts, b.parts) : partial(b.mass_parts, b.parts)}
                </td>
                <td className="r num">
                  {moneyWord(b.cost_usd)}
                  {partial(b.cost_parts, b.parts)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {other.length ? <p className="foot">Not sorted: {other.map(([k, v]) => `${v} ${OTHER_WORDS[k] ?? k}`).join(", ")}.</p> : null}

      <h2>What making in-house takes</h2>
      {rep.in_house.parts ? (
        <>
          <p className="rp">
            {rep.in_house.parts} {rep.in_house.parts === 1 ? "part" : "parts"} on your machines: {hoursWord(rep.in_house.hours)} of machine time and{" "}
            {rep.in_house.used_kg != null && rep.in_house.used_parts ? `${kg(rep.in_house.used_kg)} of material used (${kg(rep.in_house.mass_kg)} in the parts)` : `${kg(rep.in_house.mass_kg)} of material`} at the quantities checked.
          </p>
          {rep.in_house.machines.length ? (
            <div className="val-wide">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Machine</th>
                    <th scope="col">Method</th>
                    <th scope="col" className="r">
                      Parts
                    </th>
                    <th scope="col" className="r">
                      Machine time
                    </th>
                    <th scope="col" className="r">
                      Hours a year
                    </th>
                    <th scope="col" className="r">
                      Utilization
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rep.in_house.machines.map((m) => (
                    <tr key={m.machine}>
                      <td>{m.machine}</td>
                      <td>{methodWord(m.process)}</td>
                      <td className="r num">{m.parts}</td>
                      <td className="r num">{hoursWord(m.hours)}</td>
                      <td className="r num">
                        {m.available_hours ? hoursWord(m.available_hours) : "—"}
                        {m.capacity && !m.capacity.set ? <small>assumed</small> : null}
                      </td>
                      <td className="r num">{m.utilization_pct != null ? (m.overloaded ? <b className="rover">{Math.round(m.utilization_pct)}%, overloaded</b> : `${m.utilization_pct}%`) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {rep.in_house.materials?.length ? (
            <div className="val-wide">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Material</th>
                    <th scope="col" className="r">
                      Parts
                    </th>
                    <th scope="col" className="r">
                      Material used
                    </th>
                    <th scope="col" className="r">
                      In the parts
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rep.in_house.materials.map((g) => (
                    <tr key={g.material}>
                      <td>{g.material}</td>
                      <td className="r num">{g.parts}</td>
                      <td className="r num">
                        {kg(g.used_kg)}
                        {g.used_kg != null ? partial(g.used_parts, g.parts) : ""}
                      </td>
                      <td className="r num">{kg(g.part_kg)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : (
        <p className="rp muted">No part sorted to your machines.</p>
      )}

      {rep.missing?.length || rep.outside?.length ? (
        <>
          <h2>Machines you don’t have</h2>
          {rep.missing?.length ? (
            <div className="val-wide">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Needs a new machine</th>
                    <th scope="col">What it lacks</th>
                    <th scope="col" className="r">
                      Parts
                    </th>
                    <th scope="col" className="r">
                      Machine time
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rep.missing.map((g) => (
                    <tr key={`${g.process}-${g.gate}-${String(g.need ?? "")}`}>
                      <td>{methodWord(g.process)}</td>
                      <td>{g.human ?? g.gate ?? "—"}</td>
                      <td className="r num">{g.parts}</td>
                      <td className="r num">{hoursWord(g.hours)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {rep.outside?.length ? (
            <div className="val-wide">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Made outside: no machine of yours does it</th>
                    <th scope="col" className="r">
                      Parts
                    </th>
                    <th scope="col" className="r">
                      Machine time
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rep.outside.map((m) => (
                    <tr key={`${m.process}`}>
                      <td>{methodWord(m.process)}</td>
                      <td className="r num">{m.parts}</td>
                      <td className="r num">{hoursWord(m.hours)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="foot">ScaleCAD has no machine prices: these are the capabilities missing and the machine time they’d carry, not purchase costs.</p>
        </>
      ) : null}

      <h2>Biggest wins</h2>
      {rep.wins.length ? (
        <>
          <div className="val-wide">
            <table>
              <thead>
                <tr>
                  <th scope="col">Part</th>
                  <th scope="col">On</th>
                  <th scope="col" className="r">
                    Quantity
                  </th>
                  <th scope="col" className="r">
                    In-house each
                  </th>
                  <th scope="col" className="r">
                    Buy each
                  </th>
                  <th scope="col" className="r">
                    Saving at quantity
                  </th>
                </tr>
              </thead>
              <tbody>
                {rep.wins.map((w) => (
                  <tr key={`${w.part_key}-${w.quantity}`}>
                    <td>
                      {w.part_key ? <Link href={R.part(w.part_key)}>{w.file_name}</Link> : w.file_name}
                      {w.part_number ? <small>{w.part_number}</small> : null}
                    </td>
                    <td>{w.machine ?? methodWord(w.process)}</td>
                    <td className="r num">{w.quantity.toLocaleString("en-US")}</td>
                    <td className="r num">{moneyWord(w.in_house_each)}</td>
                    <td className="r num">
                      {moneyWord(w.outside_each)}
                      <small>{w.vs === "model" || !w.vs ? `ScaleCAD estimate, ${methodWord(w.outside_process)}` : "what you pay"}</small>
                    </td>
                    <td className="r num">{moneyWord(w.saving_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="foot">Your machine at its running rate against what you pay today where you gave a price, else against ScaleCAD’s estimate of the cheapest outside route at the same quantity.</p>
        </>
      ) : (
        <p className="rp muted">No in-house part has both an in-house and an outside price to compare.</p>
      )}

      <h2>Decisions recorded</h2>
      {rep.signoffs && rep.signoffs.recorded ? (
        <p className="rp">
          {rep.signoffs.signed_off} of {rep.signoffs.recorded} signed off{rep.signoffs.out_of_date ? `, ${rep.signoffs.out_of_date} of them now out of date: what they were signed off on has changed` : ""}.
        </p>
      ) : null}
      {rep.decisions.length ? (
        <div className="val-wide">
          <table>
            <thead>
              <tr>
                <th scope="col">Part</th>
                <th scope="col">Decision</th>
                <th scope="col">By</th>
                <th scope="col">Date</th>
                <th scope="col">Note</th>
                <th scope="col">Signed off</th>
              </tr>
            </thead>
            <tbody>
              {rep.decisions.map((d) => (
                <tr key={d.part_key}>
                  <td>
                    <Link href={R.part(d.part_key)}>{d.file_name}</Link>
                    {d.part_number ? <small>{d.part_number}</small> : null}
                  </td>
                  <td>
                    {d.decision}
                    {d.process || d.quantity ? <small>{[d.process ? methodWord(d.process) : null, d.quantity ? `at ${d.quantity.toLocaleString("en-US")}` : null].filter(Boolean).join(" ")}</small> : null}
                  </td>
                  <td>{d.by ?? "Not recorded"}</td>
                  <td>{dateWord(d.at)}</td>
                  <td>{d.note ?? ""}</td>
                  <td>
                    {d.signoff ? (
                      <>
                        {d.signoff.by ?? "Signed off"}, {dateWord(d.signoff.at)}
                        {d.signoff.note ? <small>{d.signoff.note}</small> : null}
                        {d.signoff.stale ? <small style={{ color: "var(--warn)", fontWeight: 600 }}>Out of date: {outOfDateText(d.signoff.stale_reason).toLowerCase()}</small> : null}
                      </>
                    ) : (
                      <span className="muted">Not signed off</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="rp muted">No decision recorded on these parts yet. Record one on a part’s Decide view.</p>
      )}

      <h2>Checked against your actuals</h2>
      <p className="rp">
        {a.parts && rep.accuracy_shown === false
          ? `${a.parts} ${a.parts === 1 ? "part has" : "parts have"} actuals: not enough to say how accurate ScaleCAD is for you (${a.min_parts} or more give a fair picture), so no accuracy figure is given yet.`
          : summaryLine(a)}
      </p>
      {a.parts && rep.accuracy_shown !== false ? (
        <div className="val-wide">
          <table>
            <thead>
              <tr>
                <th scope="col">Method</th>
                <th scope="col">Machine hours</th>
                <th scope="col">Cost per part</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <b>All methods</b>
                </td>
                <td>{statsLine(a.hours)}</td>
                <td>{statsLine(a.cost)}</td>
              </tr>
              {a.per_process.map((p) => (
                <tr key={p.process}>
                  <td>
                    {methodWord(p.process)}
                    {!p.hours.enough && !p.cost.enough ? <small>Fewer than {a.min_per_method} actuals</small> : null}
                  </td>
                  <td>{statsLine(p.hours)}</td>
                  <td>{statsLine(p.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {a.parts && rep.accuracy_shown !== false && a.hours.worst?.file_name ? (
        <p className="foot">
          Largest machine-hours miss: {a.hours.worst.file_name} ({pctWord(a.hours.worst_pct)}). Median by size {absPct(a.hours.median_abs_pct)}. Error is ScaleCAD’s estimate against your actual: +10% means ScaleCAD said 10% more.
        </p>
      ) : null}
      {rep.calibration ? (
        <p className="rp">
          Calibration in effect since {dateWord(rep.calibration.applied_at)}
          {rep.calibration.applied_by ? `, applied by ${rep.calibration.applied_by}` : ""}:{" "}
          {Object.entries(rep.calibration.factors)
            .map(([p, f]) => `${methodWord(p)}${f.hours ? `, machine time ${factorWord(f.hours)}` : ""}${f.cost ? `, cost ${factorWord(f.cost)}` : ""}`)
            .join("; ")}
          .
        </p>
      ) : null}
      <ul className="cav">
        {rep.caveats.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      {rep.coverage && (rep.coverage.unchecked.length || rep.coverage.unsorted.length) ? (
        <>
          <h2>
            Not checked ({rep.coverage.not_checked}){rep.coverage.not_sorted ? `, and checked without a machine verdict (${rep.coverage.not_sorted})` : ""}
          </h2>
          <p className="foot">They aren’t in any figure above. Check them again from the run.{rep.coverage.reasons.length === 1 ? ` All ${rep.coverage.not_checked}: ${rep.coverage.reasons[0].reason.toLowerCase()}.` : ""}</p>
          <ul className="rcols">
            {[...rep.coverage.unchecked, ...rep.coverage.unsorted].map((u, i) => (
              <li key={i}>
                {u.part}
                {rep.coverage!.reasons.length !== 1 && u.reason ? <small> {u.reason}</small> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <p className="foot">ScaleCAD pilot report · {rep.generated_at.slice(0, 16).replace("T", " ")} UTC · engine estimates and your own numbers, not quotes.</p>
    </article>
  );
}
