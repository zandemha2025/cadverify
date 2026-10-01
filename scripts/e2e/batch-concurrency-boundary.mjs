import assert from "node:assert/strict";

// Run with a CUA tab on /batch in the disposable local audit workspace.
export async function verifyBatchConcurrencyBoundary(tab) {
  const input = tab.playwright.getByRole("spinbutton", { name: "Concurrency limit" });
  assert.equal(await input.getAttribute("min"), "1");
  assert.equal(await input.getAttribute("max"), "12");
  await input.fill("13");
  assert.equal(await input.evaluate((el) => el.value), "12");
  await input.fill("-1");
  assert.equal(await input.evaluate((el) => el.value), "1");
  await input.fill("2");
  assert.equal(await input.evaluate((el) => el.value), "2");
  return { status: "PASS", checks: ["supported range 1–12", "upper/lower bounds", "valid value retained"] };
}

// Open a saved batch during a real local API outage; no mocked page responses.
export async function assertBatchReadFailure(tab) {
  const state = await tab.playwright.evaluate(() => ({
    text: document.querySelector('main')?.textContent,
    buttons: [...document.querySelectorAll('main button')].map(b => b.textContent),
  }));
  assert.match(state.text, /Could not load progress/);
  assert.match(state.text, /Could not load batch items/);
  assert.doesNotMatch(state.text, /No items found|No items match this filter/);
  assert.equal(state.buttons.includes('Cancel batch'), false,
    'An unknown batch status cannot authorize a cancellation action');
  assert.equal(state.buttons.filter(label => label === 'Try again').length, 2);
  return { status: 'PASS', checks: ['honest failed reads', 'no unknown-status cancellation', 'both reads retryable'] };
}

// Select a ZIP and enter a callback URL, leaving the secret empty.
export async function assertWebhookSecretRequired(tab) {
  const secret = tab.playwright.getByRole('textbox', { name: 'Webhook signing secret', exact: true });
  assert.equal(await secret.getAttribute('type'), 'password');
  assert.notEqual(await secret.getAttribute('required'), null);
  assert.equal(await tab.playwright.getByRole('button', { name: 'Start batch', exact: true }).isEnabled(), false);
  return { status: 'PASS', checks: ['masked required secret', 'unsigned callback submission disabled'] };
}

// After a delayed cursor response settles, only the current filter may own rows.
export async function assertBatchFilteredRows(tab, status, filenames) {
  const rows = await tab.playwright.getByRole('row').evaluateAll(elements =>
    elements.filter(row => row.querySelector('td')).map(row => ({
      filename: row.querySelector('td p')?.textContent,
      status: row.querySelectorAll('td')[1]?.textContent?.trim(),
    })));
  assert.equal(await tab.playwright.getByRole('combobox').innerText(), status.toLowerCase());
  assert.deepEqual(Array.from(rows, row => row.filename).sort(), [...filenames].sort());
  assert.ok(rows.every(row => row.status === status), 'A superseded page must not append rows under another filter');
  return { status: 'PASS', checks: ['current filter only', 'exact persisted items', 'no duplicate rows'], rows };
}

// Open a known saved analysis through a batch link during an actual API outage.
export async function assertSavedAnalysisReadFailure(tab) {
  const main = tab.playwright.getByRole('main');
  const text = await main.innerText();
  assert.match(text, /Could not load analysis/);
  assert.doesNotMatch(text, /Analysis not found|Manufacturable/);
  assert.equal(await main.getByRole('button', { name: 'Try again', exact: true }).isEnabled(), true);
  return { status: 'PASS', checks: ['failed read does not claim missing data', 'retry available', 'stale result withheld'] };
}
