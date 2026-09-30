import assert from "node:assert/strict";

// CUA check: share the real audit STEP costed at 1,923,4591,4592,5000,10000.
export async function verifyPublicCostReconciliation(tab) {
  const snapshot = await tab.playwright.domSnapshot();
  assert.match(snapshot, /At quantity 1: make by FDM \/ FFF/);
  assert.match(snapshot, /lowest-cost no-tooling route varies by quantity/);
  assert.match(snapshot, /crossover: ~4,592 units; requires redesign/);
  assert.match(snapshot, /FDM \/ FFF · quantity 1/);
  assert.match(snapshot, /\$18\.00 – \$42\.00/);
  assert.doesNotMatch(snapshot, /Make below|stays cheapest at every quantity/);
  const rows = await tab.playwright.getByRole("row").allTextContents({ timeoutMs: 5000 });
  for (const [index, quantity, process, price] of [
    [1, "1", "FDM / FFF", "$30.00"],
    [2, "923", "MJF (HP)", "$3.49"],
    [3, "4,591", "MJF (HP)", "$3.48"],
    [4, "4,592", "MJF (HP)", "$3.48"],
    [5, "5,000", "MJF (HP)", "$3.48"],
    [6, "10,000", "MJF (HP)", "$3.48"],
  ]) {
    assert.ok(rows[index].startsWith(quantity), rows[index]);
    assert.ok(rows[index].includes(process), rows[index]);
    assert.ok(rows[index].endsWith(price), rows[index]);
  }
  return { status: "PASS", reconciledRecommendations: 6, confidenceQuantity: 1, conditionalCrossover: 4592 };
}
