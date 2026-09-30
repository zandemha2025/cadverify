import assert from "node:assert/strict";

// Run with a CUA tab after importing the named demo CSV in Calibration & truth.
export async function verifyCalibrationImportFeedback(tab, { imported, skipped, error }) {
  const summary = tab.playwright.getByRole("status", { name: "Ground-truth CSV import" });
  assert.equal(await summary.count(), 1, "CSV outcome must remain visible after its toast expires");
  const text = await summary.innerText();
  assert.ok(text.includes(`${imported} imported · ${skipped} skipped`), text);
  if (error) assert.ok(text.includes(error), text);
  else assert.ok(!text.includes("line "), "Corrected import must clear old row errors");
  return { status: "PASS", imported, skipped, error: error ?? null };
}

export async function verifyCalibrationMobileWidth(tab) {
  const size = await tab.playwright.evaluate(() => {
    const el = Array.from(document.querySelectorAll("main")).at(-1);
    return el ? { width: el.clientWidth, contentWidth: el.scrollWidth } : null;
  });
  assert.ok(size, "Calibration content must be present");
  assert.ok(size.contentWidth <= size.width + 1, JSON.stringify(size));
  return { status: "PASS", ...size };
}
