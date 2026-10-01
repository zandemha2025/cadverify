// Run through CUA: import this module, then pass the CUA tab with a selected
// finding in Routing & DFM. No direct browser connection or page script injection.
export async function verifyIssueKeyboard(tab) {
  const check = (ok, message) => { if (!ok) throw new Error(message); };
  const before = await tab.playwright.domSnapshot();
  check(before.includes('Clear selected issue'), 'Select a finding before running this check.');
  const issueUrl = await tab.url();
  await tab.playwright.getByRole('tab', { name: 'Decision', exact: true }).click();
  const decision = await tab.playwright.domSnapshot();
  check(decision.includes('slider'), 'Decision must expose the quantity slider.');
  const slider = tab.playwright.getByRole('slider');
  await slider.press('Home');
  const home = await tab.playwright.domSnapshot();
  const sliderPositionBefore = Number(await slider.getAttribute('aria-valuenow'));
  await slider.press('ArrowRight');
  const quantityAfterDom = await tab.playwright.domSnapshot();
  check(/tab "Decision"[^\n]*\[selected\]/.test(quantityAfterDom), 'Quantity key changed the active tab.');
  const sliderPositionAfter = Number(await slider.getAttribute('aria-valuenow'));
  check(sliderPositionAfter > sliderPositionBefore, 'Quantity key did not move the slider.');
  check(await tab.url() === issueUrl, 'Quantity key changed the selected finding.');
  await tab.playwright.getByRole('tab', { name: 'Routing & DFM', exact: true }).click();
  const routing = await tab.playwright.domSnapshot();
  check(routing.includes('Clear selected issue'), 'Returning to routing lost selection.');
  await tab.playwright.getByRole('tab', { name: 'Routing & DFM', exact: true }).press('ArrowRight');
  await tab.playwright.getByRole('tabpanel', { name: 'Glass Box', exact: true }).waitFor({ state: 'visible' });
  const tabNavigation = await tab.playwright.domSnapshot();
  check(/tab "Glass Box"[^\n]*\[selected\]/.test(tabNavigation), 'Tab arrow did not open Glass Box.');
  check(await tab.url() === issueUrl, 'Tab navigation changed the selected finding.');
  await tab.playwright.getByRole('tab', { name: 'Routing & DFM', exact: true }).click();
  await tab.playwright.domSnapshot();
  await tab.playwright.getByRole('button', { name: 'Search and jump to a workspace', exact: true }).click();
  const dialog = await tab.playwright.domSnapshot();
  check(dialog.includes('dialog "Command palette"'), 'Command dialog did not open.');
  const input = tab.playwright.getByRole('textbox', { name: 'Jump to… Batch, History, Developer, API docs', exact: true });
  await input.fill('cad');
  await input.press('ArrowLeft');
  const typed = await tab.playwright.domSnapshot();
  check(await tab.url() === issueUrl, 'Text cursor key changed the selected finding.');
  await input.press('Escape');
  const closed = await tab.playwright.domSnapshot();
  check(!closed.includes('dialog "Command palette"'), 'Escape did not close the dialog.');
  check(await tab.url() === issueUrl && closed.includes('Clear selected issue'), 'Closing the dialog cleared the finding.');
  await tab.playwright.getByRole('button', { name: 'Next issue', exact: true }).press('Shift+ArrowRight');
  const modified = await tab.playwright.domSnapshot();
  check(await tab.url() === issueUrl, 'Modifier key chord changed the selected finding.');
  await tab.playwright.getByRole('button', { name: 'Next issue', exact: true }).press('ArrowRight');
  const next = await tab.playwright.domSnapshot();
  const nextUrl = await tab.url();
  check(nextUrl !== issueUrl && next.includes('Clear selected issue'), 'Routing arrow did not move to the next finding.');
  await tab.playwright.getByRole('button', { name: 'Previous issue', exact: true }).press('ArrowLeft');
  const previous = await tab.playwright.domSnapshot();
  check(await tab.url() === issueUrl, 'Routing arrow did not return to the original finding.');
  await tab.playwright.getByRole('button', { name: 'Clear selected issue', exact: true }).press('Escape');
  const cleared = await tab.playwright.domSnapshot();
  check(!cleared.includes('Clear selected issue') && !new URL(await tab.url()).searchParams.has('issue'), 'Escape did not clear the routing selection.');
  return { issueUrl, sliderPositionBefore, sliderPositionAfter, nextUrl, checksPassed: 9,
    states: { before, decision, home, quantityAfterDom, routing, tabNavigation, dialog, typed, closed, modified, next, previous, cleared } };
}
