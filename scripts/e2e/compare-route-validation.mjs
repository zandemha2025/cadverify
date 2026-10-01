import assert from "node:assert/strict";

export async function assertComparisonReadiness(page, process, count) {
  const row = await page.playwright.evaluate((process) => {
    const section = [...document.querySelectorAll("section")].find((el) => el.innerText.includes("DECISION VS DECISION"));
    return [...section?.querySelectorAll("span") ?? []].find((el) => el.textContent === process)?.parentElement.innerText;
  }, process);
  assert.ok(row, `Missing comparison row: ${process}`);
  assert.equal((row.match(/requires redesign/g) ?? []).length, count,
    `Every conditional price needs its saved readiness label: ${row}`);
  return { status: "PASS", process, labels: count, row };
}

export async function assertComparisonFits(page, expectedViewport) {
  const state = await page.playwright.evaluate(() => {
    const panel = [...document.querySelectorAll("main")].find((el) =>
      [...el.children].some((child) => child.tagName === "H1" && child.textContent === "Compare"));
    return panel ? { viewport: innerWidth, width: panel.clientWidth, scroll: panel.scrollWidth,
      controls: [...panel.querySelectorAll("select,input,button")].map((el) => ({
        left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right,
      })) } : null;
  });
  assert.ok(state, "Comparison must be open");
  assert.equal(state.viewport, expectedViewport, "The intended viewport must actually be active");
  assert.ok(state.scroll <= state.width + 1, JSON.stringify(state));
  assert.ok(state.controls.every((el) => el.left >= 0 && el.right <= state.viewport + 1), JSON.stringify(state.controls));
  return { status: "PASS", ...state };
}

export async function assertSelectedComparisonRecord(page, recordId) {
  const selected = await page.playwright.evaluate(() => {
    const select = [...document.querySelectorAll("select")].find((el) =>
      el.closest("label")?.textContent.trim().startsWith("A"));
    return select?.value;
  });
  assert.equal(selected, recordId, "Part Compare must retain the selected saved record");
  return { status: "PASS", recordId };
}

export async function assertComparisonIdentity(page, { idA, idB, differentCad = false }) {
  for (const [label, id] of [["A", idA], ["B", idB]]) {
    const selected = await page.playwright.evaluate((label) =>
      [...document.querySelectorAll("select")].find((el) =>
        el.closest("label")?.textContent.trim().startsWith(label))?.value, label);
    assert.equal(selected, id, `Comparison ${label} must use the intended CAD record`);
  }
  assert.equal(await page.playwright.getByText("Different CAD inputs. Price differences may reflect geometry as well as costing inputs.", { exact: true }).isVisible(), differentCad);
}

export async function assertComparisonOptions(page, expectedIds) {
  const ids = await page.playwright.evaluate(() => {
    const select = [...document.querySelectorAll("select")].find((el) => el.closest("label")?.textContent.trim().startsWith("A"));
    return [...select?.options ?? []].map((option) => option.value).filter(Boolean);
  });
  assert.equal(new Set(ids).size, ids.length, "Older pages must not duplicate a directly selected record");
  assert.equal(JSON.stringify([...ids].sort()), JSON.stringify([...expectedIds].sort()), "Every requested saved record must be selectable");
  return ids.length;
}

export async function assertOpenDecisionOptions(page, expectedIds) {
  const labels = await page.playwright.getByRole("option").allTextContents({});
  assert.equal(new Set(labels).size, labels.length, "Picker labels must distinguish saved records");
  const suffixes = labels.map((label) => label.match(/#([A-Z0-9]{6})$/)?.[1]).sort();
  assert.equal(JSON.stringify(suffixes), JSON.stringify(expectedIds.map((id) => id.slice(-6)).sort()));
  return labels.length;
}

export async function assertComparisonCleared(page) {
  assert.equal(await page.playwright.getByRole("heading", { name: "Recommended unit cost by quantity", exact: true }).isVisible(), false,
    "Changing either decision must remove the previous pair's result until Compare is run again");
  assert.equal(await page.playwright.getByRole("button", { name: "Compare", exact: true }).isEnabled(), true);
  return { status: "PASS", previousResultCleared: true };
}

export async function assertComparisonPending(page) {
  const disabled = await page.playwright.evaluate(() =>
    [...document.querySelectorAll('[role="combobox"]')].map((el) => el.hasAttribute("disabled")));
  assert.equal(JSON.stringify(disabled), "[true,true]", "An in-flight comparison must retain its selected pair");
  return { status: "PASS", pickersDisabled: true };
}

export async function assertSelectedComparisonUnavailable(page) {
  assert.equal(await page.playwright.getByText("Could not load the selected comparison — Cost decision not found", { exact: true }).isVisible(), true);
  assert.equal(await page.playwright.getByRole("button", { name: "Retry records", exact: true }).isEnabled(), true);
  assert.equal(await page.playwright.getByText("Nothing to compare yet.", { exact: true }).isVisible(), false);
  return { status: "PASS", missingSelectedRecord: "recoverable error" };
}

export async function assertDecisionPickerFits(page, expectedViewport) {
  const state = await page.playwright.evaluate(() => ({
    viewport: innerWidth, width: document.documentElement.scrollWidth,
    controls: [...document.querySelectorAll('[role="combobox"]')].map((el) => ({
      left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right,
    })),
  }));
  assert.equal(state.viewport, expectedViewport);
  assert.equal(state.controls.length, 2);
  assert.ok(state.width <= state.viewport + 1, JSON.stringify(state));
  assert.ok(state.controls.every((el) => el.left >= 0 && el.right <= state.viewport + 1), JSON.stringify(state));
  return { status: "PASS", ...state };
}

// CUA assertion; expected values come from the native saved-report export.
export async function assertComparedRoute(page, { quantity, process, makePrice, toolPrice }) {
  const text = await page.playwright.locator("section").filter({ hasText: "ROUTE VS ROUTE" }).innerText();
  assert.ok(text.includes(`qty ${quantity} —`), `Missing computed quantity ${quantity}`);
  assert.ok(text.includes(`${process} (make-now)`), `Wrong quantity-specific process: ${text}`);
  assert.ok(text.includes(`make ${makePrice} `), `Wrong quantity-specific make price: ${text}`);
  assert.ok(text.includes(`acquire ${toolPrice} `), `Wrong tooling price: ${text}`);
  assert.ok(text.includes("requires redesign"), "Conditional tooling must retain its redesign requirement");
  return { status: "PASS", quantity, process, makePrice, toolPrice, text };
}
