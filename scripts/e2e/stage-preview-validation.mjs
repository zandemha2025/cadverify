import assert from "node:assert/strict";

export async function assertStagePreviewFailure(page, filename) {
  const state = await page.playwright.evaluate(() => ({
    title: document.querySelector('.cv-verify-stage h1')?.textContent,
    mode: document.querySelector('[data-testid="verify-stage-render-mode"]')?.getAttribute('data-render-state'),
    message: document.querySelector('.cv-verify-stage [role="status"]')?.textContent,
    xrayDisabled: document.querySelector('.cv-verify-stage-controls button')?.disabled,
    canReplace: [...document.querySelectorAll('button')].some(button => button.textContent === 'Check my CAD' && !button.disabled),
    validationError: document.body.textContent.includes('No routing, DFM, or should-cost verdict was produced'),
  }));
  assert.equal(state.title, filename, 'A bad preview must retain the workspace and selected filename');
  assert.equal(state.mode, 'preview-unavailable', 'A failed preview must not claim real geometry');
  assert.match(state.message, /Could not draw this part/);
  assert.equal(state.xrayDisabled, true, 'Unavailable preview controls must be disabled');
  assert.equal(state.canReplace, true, 'A replacement file must be selectable without reloading');
  assert.equal(state.validationError, true, 'The real validation refusal must remain visible');
  return { status: 'PASS', ...state };
}

export async function assertStageLayout(page) {
  const boxes = await page.playwright.evaluate(() => {
    const rect = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const { x, y, width, height } = element.getBoundingClientRect();
      return { x, y, width, height };
    };
    return {
      title: rect(".cv-verify-stage-title"),
      context: rect(".cv-verify-stage-context-card"),
      canvas: rect(".cv-verify-stage canvas"),
      controls: rect(".cv-verify-stage-controls"),
      stage: rect(".cv-verify-stage"),
      mode: document.querySelector('[data-testid="verify-stage-render-mode"]')?.getAttribute("data-render-state"),
    };
  });
  const overlaps = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width
    && a.y < b.y + b.height && b.y < a.y + a.height;
  assert.ok(boxes.title && boxes.context && boxes.canvas && boxes.stage, "Real preview and labels must exist");
  assert.equal(overlaps(boxes.title, boxes.context), false, "Context must not cover the filename or dimensions");
  assert.equal(overlaps(boxes.title, boxes.canvas), false, "Title must leave room for the CAD preview");
  assert.equal(overlaps(boxes.context, boxes.canvas), false, "Context must leave room for the CAD preview");
  assert.ok(boxes.controls, "Preview controls must exist");
  assert.equal(overlaps(boxes.controls, boxes.canvas), false, "Controls must not cover CAD geometry");
  assert.ok(boxes.canvas.width >= 200 && boxes.canvas.height >= 200, "Preview must remain usable");
  for (const key of ["title", "context", "canvas", "controls"]) {
    assert.ok(boxes[key].x >= boxes.stage.x - 1
      && boxes[key].x + boxes[key].width <= boxes.stage.x + boxes.stage.width + 1, `${key} must fit the stage width`);
  }
  assert.ok(["real-shell", "real-stl", "real-assembly"].includes(boxes.mode), "Proof requires actual geometry");
  return { status: "PASS", ...boxes };
}
