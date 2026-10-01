import assert from "node:assert/strict";

// Run with a CUA-controlled tab and the report downloaded through its UI.
export async function assertSavedRecordLinks(page, expectedId) {
  const links = page.playwright.getByRole("link", { name: "Open the record →", exact: true });
  assert.equal(await links.count(), 2, "Both saved-record actions must identify a record");
  const hrefs = [];
  for (const link of await links.all()) {
    const href = await link.getAttribute("href");
    assert.equal(href, `/cost-decisions/${expectedId}`);
    hrefs.push(href);
  }
  return { status: "PASS", hrefs };
}

export async function assertRecordEstimateContext(page, report) {
  const estimates = report.estimates.filter(
    (e) => e.process === report.decision.make_now_process && !e.environment_excluded,
  );
  const estimate = estimates.reduce((a, b) => b.quantity > a.quantity ? b : a);
  const context = page.playwright.getByTestId("record-estimate-context");
  assert.equal(await context.count(), 1, "Saved receipts must identify their quantity");
  const text = await context.innerText();
  assert.ok(text.includes(`quantity ${estimate.quantity.toLocaleString("en-US")}`), text);
  assert.ok(text.includes(estimate.material), text);
  return { status: "PASS", context: text, process: estimate.process, quantity: estimate.quantity };
}
