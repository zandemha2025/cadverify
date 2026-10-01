// Pass Playwright's page in CI, or tab.playwright from cua_repl locally.
import assert from "node:assert/strict";

export async function assertApprovalDraftGuard(page, dirty) {
  assert.equal(
    await page.getByRole("button", { name: "Approve", exact: true }).isEnabled(),
    !dirty,
    "approval must wait for the displayed outcome note to be saved",
  );
  if (dirty) {
    assert.match(
      await page.getByTestId("record-disposition-unsaved").innerText(),
      /Unsaved outcome note/,
    );
  }
}
