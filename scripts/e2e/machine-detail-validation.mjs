import assert from "node:assert/strict";

export async function assertMachineDetailOutage(page) {
  const state = await page.playwright.evaluate(() => {
    const sections = [...document.querySelectorAll('section')];
    const rate = sections.find(s => s.textContent.includes('RATE HISTORY'));
    const records = sections.find(s => s.textContent.includes('PARTS ROUTED HERE'));
    return {
      rateText: rate?.textContent,
      recordsText: records?.textContent,
      retryRates: [...(rate?.querySelectorAll('button') ?? [])].some(b => b.textContent === 'Retry rates'),
      retryRecords: [...(records?.querySelectorAll('button') ?? [])].some(b => b.textContent === 'Retry records'),
    };
  });
  assert.ok(state.rateText && state.recordsText, 'Machine details must remain visible');
  assert.doesNotMatch(state.rateText, /no governed rate card in effect|current effective card: default/,
    'Failed reads cannot claim the default rate context');
  assert.doesNotMatch(state.recordsText, /nothing routed yet/,
    'Failed reads cannot claim an empty history');
  assert.equal(state.retryRates, true, 'Rate reads must be retryable');
  assert.equal(state.retryRecords, true, 'Record reads must be retryable');
  return { status: 'PASS', ...state };
}
