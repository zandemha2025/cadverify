import assert from "node:assert/strict";

export async function assertAssignedProgramOpens(page, program) {
  assert.equal(await page.playwright.getByRole("heading", { name: program, exact: true }).count(), 1,
    "Open program must retain the part's declared program");
  assert.equal(await page.playwright.getByRole("heading", { name: "Programs", exact: true }).count(), 0,
    "An assigned-program link must open its detail");
  return { status: "PASS", program };
}

// CUA-controlled browser check; enter the draft before invoking this assertion.
export async function assertInvalidProgramVolume(page, name, draft) {
  const state = await page.playwright.evaluate((name) => {
    const el = [...document.querySelectorAll("input")].find((input) => input.title === name || input.getAttribute("aria-label") === name);
    return el ? { value: el.value, invalid: el.getAttribute("aria-invalid") } : null;
  }, name);
  assert.ok(state, "Volume input must be present");
  assert.equal(state.value, draft, "Never silently rewrite the user's quantity");
  assert.equal(state.invalid, "true", "Invalid quantities must be identified before saving");
  return { status: "PASS", ...state };
}

export async function assertProgramFitsViewport(page) {
  const state = await page.playwright.evaluate(() => {
    const panel = document.querySelector('[data-screen-label="Program detail"]');
    return panel ? { width: panel.clientWidth, scrollWidth: panel.scrollWidth } : null;
  });
  assert.ok(state, "Program detail must be visible");
  assert.ok(state.scrollWidth <= state.width + 1, JSON.stringify(state));
  return { status: "PASS", ...state };
}

export async function assertPartialProgramExposure(page, included, total) {
  const snapshot = await page.playwright.domSnapshot();
  const expected = `${included} of ${total} parts included`;
  assert.ok(snapshot.includes(expected), `Missing partial-total label: ${expected}`);
  return { status: "PASS", included, total };
}

export async function assertRetainedProgramVolume(page, filename, expected) {
  const actual = await page.playwright.evaluate((filename) => {
    const input = [...document.querySelectorAll("input")].find((el) => el.getAttribute("aria-label") === `Optional annual volume for ${filename}`);
    return input?.value;
  }, filename);
  assert.equal(actual, String(expected), "Reassignment must retain the existing demand");
  return { status: "PASS", value: actual };
}
