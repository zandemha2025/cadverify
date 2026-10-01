/** Run through CUA on a local saved-part standing with the named test BOM. */
import assert from 'node:assert/strict';

export async function checkBomLink(page, { assemblyKey, childRef, rootsPerYear }) {
  const disclosure = page.playwright.getByText('Link this part to a saved BOM', { exact: true });
  assert.equal(await disclosure.count(), 1, 'saved parts need a visible BOM-link control');
  const form = page.playwright.getByRole('form', { name: 'Part BOM link', exact: true });
  if (!(await form.isVisible())) await disclosure.click();
  await form.getByLabel('Saved BOM assembly name', { exact: true }).fill(assemblyKey);
  await form.getByLabel('Part reference in BOM', { exact: true }).fill('missing-component-147');
  await form.getByLabel('Root assemblies per year (optional)', { exact: true }).fill(String(rootsPerYear));
  await form.getByRole('button', { name: 'Save BOM link', exact: true }).click();
  await form.getByRole('alert').waitFor({ state: 'visible' });
  assert.match(await form.getByRole('alert').innerText(), /does not contain that part/);
  await form.getByLabel('Part reference in BOM', { exact: true }).fill(childRef);
  assert.equal(await form.getByRole('alert').count(), 0, 'editing clears the previous error');
  await form.getByRole('button', { name: 'Save BOM link', exact: true }).click();
  await form.getByRole('status').waitFor({ state: 'visible' });
  assert.match(await form.getByRole('status').innerText(), /BOM link saved/);
  assert.equal(await form.getByRole('button', { name: 'Remove BOM link', exact: true }).isEnabled(), true);
  return { invalidReferenceRejected: true, editClearsError: true, validLinkSaved: true };
}
