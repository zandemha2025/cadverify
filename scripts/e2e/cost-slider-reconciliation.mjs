import assert from "node:assert/strict";

// Run through CUA after costing the real audit STEP at 1,50,123,5000,10000.
export async function verifyCostSliderReconciliation(tab) {
  const slider = tab.playwright.getByRole("slider");
  const readout = (label) => tab.playwright.evaluate((text) => {
    const label = [...document.querySelectorAll("span")].find((el) => el.textContent === text);
    return label?.parentElement?.innerText ?? "";
  }, label);
  await slider.press("Home");
  for (let i = 0; i < 42; i++) await slider.press("PageUp");
  for (let i = 0; i < 5; i++) await slider.press("ArrowRight");
  assert.match(await readout("At quantity"), /50\s*units/);
  assert.match(await readout("Cost / unit"), /\$3\.80/);
  await slider.press("End");
  assert.match(await readout("Lead time · qty 10,000"), /7–13/);
  assert.match(await readout("Cost / unit"), /\$3\.48/);
  await slider.press("ArrowLeft");
  assert.equal(await tab.playwright.getByText("Approx. cost / unit", { exact: true }).count(), 1);
  assert.match(await readout("Lead time · qty 10,000"), /7–13/);
  return { status: "PASS", quantity50: 3.80, quantity10000: 3.48, lead10000Days: [7, 13], uncostedQuantityLabeledApproximate: true };
}
