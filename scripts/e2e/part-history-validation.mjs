import assert from "node:assert/strict";

// Run against the standing of a real part via CI or native CUA tab.playwright.
export async function assertPartHistory(page, expectedIds, { hasMore = false } = {}) {
  const history = page.getByRole("region", { name: "Part cost history", exact: true });
  const ids = await history.locator("[data-cost-decision-id]").evaluateAll(
    (rows) => rows.map((row) => row.getAttribute("data-cost-decision-id"))
  );
  assert.equal(JSON.stringify(ids), JSON.stringify(expectedIds), "History must contain exactly this part's records in cursor order");
  assert.equal(new Set(ids).size, ids.length, "Pagination must not duplicate decisions");
  assert.equal(await history.getByRole("button", { name: "Load older decisions", exact: true }).isVisible(), hasMore);
  assert(!(await history.getByRole("alert").isVisible()));
  return ids;
}
