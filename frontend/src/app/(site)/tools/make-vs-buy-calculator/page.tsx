import { SiteShell } from "@/components/site/site-shell";
import { growthMetadata } from "@/components/site/growth-page";
import { GrowthActions, GrowthLink } from "@/components/site/growth-actions";
import { MakeBuyCalculator } from "@/components/site/make-buy-calculator";

export const metadata = growthMetadata("/tools/make-vs-buy-calculator", "Free make vs buy calculator", "Compare manufacturing and supplier costs at your quantity. Calculate make-versus-buy totals, cost per part and break-even volume. No signup required.");

export default function CalculatorPage() {
  return <SiteShell><div className="growth"><header className="growth-hero"><GrowthLink href="/resources" className="growth-eyebrow">Resources / Free tool</GrowthLink><h1>Make vs buy calculator</h1><p className="growth-intro">Does this part belong on your floor or with a supplier? Compare fixed and per-part costs over the same quantity. See where the answer changes.</p><p className="growth-terms">No signup. Calculations run in your browser; entered costs and results are not sent to our analytics.</p></header>
    <MakeBuyCalculator />
    <div className="growth-body">
      <section><h2>The calculation, in full</h2><p>Make total = make fixed cost + quantity × make variable cost per part.</p><p>Buy total = buy fixed cost + quantity × landed buy cost per part.</p><p>Equality quantity = (make fixed − buy fixed) ÷ (buy variable − make variable). When variable rates match, there is no unique crossover. Identical fixed and variable costs are equal at every quantity. A zero or negative crossover is outside positive production quantities.</p><p>Totals use the entered values before display rounding. Both routes use USD and the same time period. Constant per-part costs are assumed; quantity discounts, capacity steps and yield changes need separate scenarios.</p></section>
      <section><h2>Example you can reproduce</h2><p>With $2,000 fixed and $12 per part to make, versus $200 fixed and $18 landed per part to buy, both routes cost $5,600 at 300 parts. At 500 parts, making costs $8,000 and buying costs $9,200. These are illustrative inputs, not supplier prices or a customer result.</p><GrowthLink href="/guides/make-vs-buy-analysis" className="growth-next">Read the complete make-versus-buy guide →</GrowthLink></section>
      <section><h2>What should you include?</h2><p>Use avoidable costs for the decision. Include programming, setup and fixtures where they apply. Include finishing, inspection and freight on both routes consistently. If your machine-hour rate already includes an operator, do not add the same labor again. Exclude sunk costs that do not change between alternatives.</p><p>Run a second scenario with different demand, cycle time or supplier price. A small input change that reverses the result is a reason to gather better evidence.</p></section>
      <section className="growth-callout"><h2>First, can your machines make it?</h2><p>The calculator starts from your costs. ScaleCAD starts from your part and helps you review manufacturability, machine capabilities and the assumptions behind the estimate.</p><GrowthActions /><GrowthLink href="/solutions/dfm-software" className="growth-next">See the DFM workflow →</GrowthLink></section>
    </div>
  </div></SiteShell>;
}
