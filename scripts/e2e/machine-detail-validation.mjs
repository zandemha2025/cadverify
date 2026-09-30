import assert from "node:assert/strict";

export async function assertListReadFailure(page, kind) {
  const state = await page.playwright.evaluate(() => ({
    text: document.querySelector('main main')?.textContent,
    buttons: [...document.querySelectorAll('main button')].map(b => b.textContent),
  }));
  assert.match(state.text, /couldn't load/);
  assert.doesNotMatch(state.text, /No records yet|Declare your floor\./,
    'An unavailable list must not claim that saved data is absent');
  assert.ok(state.buttons.includes(kind === 'machines' ? 'Retry inventory' : 'Retry records'));
  return { status: 'PASS', kind };
}

export async function assertMachineDetailOutage(page) {
  const state = await page.playwright.evaluate(() => {
    const sections = [...document.querySelectorAll('section')];
    const rate = sections.find(s => s.textContent.includes('RATE HISTORY'));
    const records = sections.find(s => s.textContent.includes('RECENT RECORDS FOR THIS PROCESS'));
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
  assert.doesNotMatch(state.recordsText, /No saved decisions recommending/,
    'Failed reads cannot claim an empty history');
  assert.equal(state.retryRates, true, 'Rate reads must be retryable');
  assert.equal(state.retryRecords, true, 'Record reads must be retryable');
  return { status: 'PASS', ...state };
}
