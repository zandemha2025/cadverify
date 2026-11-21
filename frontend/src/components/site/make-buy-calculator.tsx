"use client";

import { useState } from "react";
import { calculateMakeBuy, type MakeBuyInputs } from "@/lib/make-buy-calculator";
import { track } from "@/lib/analytics";

const example = { quantity: "500", makeFixed: "2000", makeVariable: "12", buyFixed: "200", buyVariable: "18" };
const fields: { key: keyof MakeBuyInputs; label: string; help: string }[] = [
  { key: "quantity", label: "Quantity (parts)", help: "Use the same order or planning period for both routes." },
  { key: "makeFixed", label: "Make: fixed cost (USD)", help: "Fixtures, programming and other costs incurred once for this quantity." },
  { key: "makeVariable", label: "Make: variable cost per part (USD)", help: "Material, machine time, labor and secondary operations. Avoid double-counting labor in a loaded rate." },
  { key: "buyFixed", label: "Buy: fixed cost (USD)", help: "One-time supplier tooling, qualification or order charges." },
  { key: "buyVariable", label: "Buy: landed cost per part (USD)", help: "Supplier unit price plus freight, duties and other per-part costs." },
];
const dollars = (value: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);

export function MakeBuyCalculator() {
  const [values, setValues] = useState(example);
  const [edited, setEdited] = useState(false);
  let result: ReturnType<typeof calculateMakeBuy> | null = null;
  let error = "";
  try {
    if (Object.values(values).some(value => value.trim() === "")) throw new Error("Fill in every field. Use 0 for a cost that does not apply.");
    result = calculateMakeBuy({ quantity: Number(values.quantity), makeFixed: Number(values.makeFixed), makeVariable: Number(values.makeVariable), buyFixed: Number(values.buyFixed), buyVariable: Number(values.buyVariable) });
  } catch (problem) { error = problem instanceof Error ? problem.message : "Check your inputs."; }

  function update(key: keyof MakeBuyInputs, value: string) {
    setValues(current => ({ ...current, [key]: value }));
    if (!edited) {
      // Deliberately exclude entered costs, quantities and computed results.
      track("calculator_started", { surface: "site", tool: "make-vs-buy", $pathname: "/tools/make-vs-buy-calculator" });
      setEdited(true);
    }
  }

  return <div className="growth-calculator">
    <form className="growth-inputs" onSubmit={event => event.preventDefault()} aria-label="Make versus buy inputs" data-private>
      <p>{edited ? "Your planning inputs" : "Illustrative example loaded — replace with your own inputs."}</p>
      {fields.map(field => <label key={field.key} htmlFor={field.key}>{field.label}<small id={`${field.key}-help`}>{field.help}</small><input id={field.key} type="number" inputMode={field.key === "quantity" ? "numeric" : "decimal"} min={field.key === "quantity" ? 1 : 0} max={1_000_000_000} step={field.key === "quantity" ? 1 : "any"} required value={values[field.key]} onChange={event => update(field.key, event.target.value)} aria-describedby={`${field.key}-help${error ? " calculator-error" : ""}`} /></label>)}
      <button className="cv-button cv-button-secondary" type="button" onClick={() => { setValues(example); setEdited(false); }}>Reset example</button>
    </form>
    <section className="growth-results" aria-live="polite" aria-atomic="true" data-private>
      {result ? <>
        <h2>{result.cheaper === "equal" ? "The modeled costs are equal." : `${result.cheaper === "make" ? "Making" : "Buying"} has the lower modeled cost.`}</h2>
        <p>At {Number(values.quantity).toLocaleString("en-US")} parts, the difference is {dollars(result.savings)} for this quantity.</p>
        <dl><div><dt>Make total</dt><dd>{dollars(result.makeTotal)}</dd></div><div><dt>Buy total</dt><dd>{dollars(result.buyTotal)}</dd></div><div><dt>Make per part</dt><dd>{dollars(result.makeUnit)}</dd></div><div><dt>Buy per part</dt><dd>{dollars(result.buyUnit)}</dd></div><div><dt>Equality quantity</dt><dd>{result.crossover !== null ? `${result.crossover.toLocaleString("en-US", { maximumFractionDigits: 4 })} parts` : result.crossoverType === "all" ? "Equal at every quantity" : "No positive crossover"}</dd></div></dl>
        {result.crossover !== null && <p>The equality quantity can be fractional. Compare the whole quantities on either side before selecting an order size.</p>}
        <p>This compares the costs you enter. It does not verify machine fit, manufacturability, available capacity or supplier performance.</p>
      </> : <p id="calculator-error" className="growth-error">{error}</p>}
    </section>
  </div>;
}
