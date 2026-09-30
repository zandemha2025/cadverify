// Use a CI Playwright page or a native CUA tab.playwright binding.
import assert from "node:assert/strict";

export async function assertHistoryLinks(page, prefix) {
  const rows = await page.locator("tbody tr").evaluateAll((elements) =>
    elements.map((row) => {
      const link = row.querySelector("td a");
      return { href: link?.getAttribute("href"), tabIndex: link?.tabIndex };
    }),
  );
  assert(rows.length > 0, "history must contain records for this check");
  for (const row of rows) {
    assert(row.href?.startsWith(prefix), "every history record needs a native detail link");
    assert.equal(row.tabIndex, 0, "record links must be keyboard reachable");
  }
}

export async function openHistoryRecordWithKeyboard(page, href) {
  const link = page.locator(`tbody a[href="${href}"]`);
  await link.press("Enter");
  await page.waitForURL(`**${href}`);
}
