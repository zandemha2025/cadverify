import assert from "node:assert/strict";

// Use after opening a real triage row, via CI or a native CUA tab.playwright.
export async function assertTriagePartDestination(page, filename) {
  assert(await page.getByRole("button", { name: "← PARTS", exact: true }).isVisible(),
    "A triage row must open the part standing, not the unfiltered catalog");
  const paragraphs = await page.locator("p").allTextContents({});
  assert(paragraphs.some((text) => text.trim() === filename),
    "The standing must identify the exact part selected in triage");
  assert(await page.getByRole("button", { name: "Re-verify", exact: true }).isVisible());
}
