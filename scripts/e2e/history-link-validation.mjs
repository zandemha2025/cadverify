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

export async function assertHistoryVerdict(page, expected) {
  assert.equal(
    (await page.getByRole("combobox", { name: "Verdict filter" }).innerText()).trim(),
    expected,
  );
  const verdicts = await page.locator("tbody tr td:nth-child(2)").allTextContents({});
  assert(verdicts.every((value) => value.trim() === expected), "rows must match the selected verdict, including after delayed responses");
  if (!verdicts.length) {
    assert(await page.getByText("No analyses match this filter", { exact: true }).isVisible());
  }
}
