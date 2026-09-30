import assert from "node:assert/strict";

// CUA check: share the real 20 × 15 × 10 mm audit STEP DFM analysis.
export async function verifyPublicAnalysisReconciliation(tab) {
  assert.equal(await tab.playwright.getByText("Recommended route: FDM / FFF", { exact: true }).count(), 1);
  const rows = await tab.playwright.getByRole("row").allTextContents({ timeoutMs: 5000 });
  assert.equal(rows.length, 22);
  assert.match(rows[1], /FDM \/ FFF100%Pass/);
  const details = tab.playwright.locator("details").filter({hasText: "Injection Molding issues (4)"});
  await details.locator("summary").click();
  assert.equal(await details.getByText("114838 sidewall faces (100.0% of sidewall area) below 1.0° draft for injection_molding.", { exact: true }).isVisible(), true);
  const snapshot = await tab.playwright.domSnapshot();
  assert.match(snapshot, /20\.0 x 15\.0 x 10\.0 mm/);
  assert.match(snapshot, /Findings below apply to each named process/);
  return { status: "PASS", processRows: 21, injectionMoldingFindings: 4, dimensionsMm: [20, 15, 10] };
}
