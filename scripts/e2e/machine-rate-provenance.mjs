import assert from "node:assert/strict";

// CUA: run on Verify after declaring a test machine with no governed rate card.
export async function verifyDeclaredMachineRate(tab, machineName, rateText) {
  assert.equal(await tab.playwright.getByRole("button", {
    name: "Default rate card — open Calibration & truth", exact: true,
  }).count(), 1, "A manual machine rate must not imply a governed SHOP card");
  const machineCost = tab.playwright.getByRole("button", { name: /^MACHINE TIME ● USER / });
  assert.equal(await machineCost.count(), 1, "Machine cost must retain USER provenance");
  await machineCost.click();
  const text = await tab.playwright.getByRole("main").first().innerText({});
  assert.ok(text.includes(`fitted machine '${machineName}', its OWN declared rate`));
  assert.ok(text.includes(`declared rate ${rateText}/hr`));
  assert.ok(text.includes("any capital adjustment is shown in the machine-cost derivation above"));
  assert.ok(!text.includes("your machine's own marginal rate"));
  assert.ok(!text.includes("assumption at SHOP rates"));
  return { status: "PASS", machineName, declaredRate: rateText, provenance: "USER", governed: false };
}
