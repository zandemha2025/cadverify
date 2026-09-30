import assert from "node:assert/strict";

// Run through CUA after uploading a real part; report is its native JSON export.
export async function verifyDfmMatrix(tab, report) {
  await tab.playwright.getByRole("tab", { name: "Routing & DFM", exact: true }).click();
  const panel = tab.playwright.getByRole("tabpanel", { name: "Routing & DFM", exact: true });
  const rows = await panel.getByRole("table").locator("tbody tr").allTextContents({});
  const costed = new Set(report.estimates.map((e) => e.process));
  assert.equal(rows.length, report.engine_feasibility.length);
  for (const [index, f] of report.engine_feasibility.entries()) {
    assert.equal(rows[index].includes("feasibility-only"), !costed.has(f.process), f.process);
    assert.ok(rows[index].includes(`${(f.score * 100).toFixed(0)}%`), `${f.process} suitability`);
    if (f.blockers?.length) assert.ok(rows[index].includes(f.blockers[0]), `${f.process} first blocker`);
  }
  const text = await panel.innerText({});
  const different = Boolean(report.decision?.make_now_process && report.routing?.recommended_process &&
    report.decision.make_now_process !== report.routing.recommended_process);
  assert.equal(text.includes("Review the routing reasons and DFM findings when choosing."), different);
  assert.ok(!text.includes("Both are costed."));
  if (report.decision?.make_now_process) {
    assert.ok(text.includes(`cost pick · qty ${Math.min(...report.quantities).toLocaleString()}`));
  }
  const overflow = await tab.playwright.evaluate(() => Array.from(document.querySelectorAll('table')).map((table) => ({
    width: table.getBoundingClientRect().width,
    available: table.parentElement.clientWidth,
    overflowX: getComputedStyle(table.parentElement).overflowX,
  })));
  for (const table of overflow) {
    if (table.width > table.available) assert.equal(table.overflowX, "auto", "Narrow tables must scroll instead of clipping blockers");
  }
  return { status: "PASS", processes: rows.length, costed: costed.size,
    blockerRows: report.engine_feasibility.filter((f) => f.blockers?.length).length,
    differentRecommendations: different };
}
