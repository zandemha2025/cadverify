import assert from "node:assert/strict";

export async function assertSessionUnavailable(page, expectedPath) {
  assert.equal(new URL(await page.url()).pathname, expectedPath, "An unavailable verifier must preserve the requested page");
  await page.playwright.getByRole("heading", { name: "Page temporarily unavailable", exact: true }).waitFor({ state: "visible" });
  assert.equal(await page.playwright.getByRole("heading", { name: "Page temporarily unavailable", exact: true }).isVisible(), true);
  assert.equal(await page.playwright.getByRole("button", { name: "Try again", exact: true }).isEnabled(), true);
  assert.equal(await page.playwright.getByRole("textbox", { name: "Email", exact: true }).isVisible(), false);
  assert.equal(await page.playwright.getByRole("navigation", { name: "Domains", exact: true }).isVisible(), false,
    "The authenticated workspace must not render until session verification succeeds");
  return { status: "PASS", requestedPath: expectedPath, retryAvailable: true, protectedShellWithheld: true };
}
