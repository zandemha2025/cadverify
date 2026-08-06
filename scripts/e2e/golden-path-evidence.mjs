import path from "node:path";

export const GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION = 2;
export const LEGACY_GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION = 1;

export const TERMINAL_FORBIDDEN_VISIBLE = Object.freeze([
  "COMPUTING",
  "Loading",
]);

// These paths were proven to have misleading or incomplete primary captures in
// the exhaustive visual audit. Their release evidence must now contain each
// named same-moment state. Other paths may be migrated to v2 incrementally, but
// cannot impersonate one of these contracts with a legacy screenshot.
export const REQUIRED_VISUAL_STAGES = Object.freeze({
  "AUTH-03": Object.freeze(["invalid-credentials"]),
  "VER-05": Object.freeze(["terminal"]),
  "VER-09": Object.freeze([
    "records-375x812",
    "records-768x1024",
    "records-1440x900",
  ]),
  "FAIL-01": Object.freeze(["failure", "recovery"]),
  "FAIL-02": Object.freeze(["failure", "recovery"]),
  "FAIL-03": Object.freeze(["failure", "recovery"]),
  "FAIL-08": Object.freeze(["failure", "recovery"]),
  "FAIL-10": Object.freeze(["failure", "recovery"]),
});

export const REQUIRED_VISUAL_STAGE_TEXT = Object.freeze({
  "AUTH-03": Object.freeze({
    "invalid-credentials": Object.freeze(["Invalid email or password."]),
  }),
  "VER-05": Object.freeze({
    terminal: Object.freeze(["What it really takes", "Open the record"]),
  }),
  "VER-09": Object.freeze({
    "records-375x812": Object.freeze(["Open governance"]),
    "records-768x1024": Object.freeze(["Open governance"]),
    "records-1440x900": Object.freeze(["Open governance"]),
  }),
  "FAIL-01": Object.freeze({
    failure: Object.freeze(["We couldn’t read this file."]),
    recovery: Object.freeze(["Open the record"]),
  }),
  "FAIL-02": Object.freeze({
    failure: Object.freeze(["This part couldn’t be tessellated."]),
    recovery: Object.freeze(["Open the record"]),
  }),
  "FAIL-03": Object.freeze({
    failure: Object.freeze(["Verification is temporarily busy.", "Retry verification"]),
    recovery: Object.freeze(["Open the record"]),
  }),
  "FAIL-08": Object.freeze({
    failure: Object.freeze(["Cost history is temporarily unavailable. Retry shortly.", "Try again"]),
    recovery: Object.freeze(["Saved decisions"]),
  }),
  "FAIL-10": Object.freeze({
    failure: Object.freeze(["Could not load progress", "Try again"]),
    recovery: Object.freeze(["1 / 1", "Download CSV"]),
  }),
});

export const REQUIRED_VISUAL_STAGE_FORBIDDEN_TEXT = Object.freeze({
  "VER-09": Object.freeze({
    "records-375x812": Object.freeze(["Verification is running."]),
    "records-768x1024": Object.freeze(["Verification is running."]),
    "records-1440x900": Object.freeze(["Verification is running."]),
  }),
  "FAIL-01": Object.freeze({
    recovery: Object.freeze(["We couldn’t read this file."]),
  }),
  "FAIL-02": Object.freeze({
    recovery: Object.freeze(["This part couldn’t be tessellated."]),
  }),
  "FAIL-03": Object.freeze({
    recovery: Object.freeze(["Verification is temporarily busy."]),
  }),
  "FAIL-08": Object.freeze({
    recovery: Object.freeze(["Cost history is temporarily unavailable. Retry shortly."]),
  }),
  "FAIL-10": Object.freeze({
    recovery: Object.freeze(["Could not load progress"]),
  }),
});

const REQUIRED_OBSERVED_FIELDS = [
  "url",
  "visible",
  "persisted",
  "numeric",
  "authorization",
  "recovery",
];

function nonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function nonEmptyStringArray(value) {
  return Array.isArray(value) && value.length > 0 && value.every(nonEmptyString);
}

function stringArray(value) {
  return Array.isArray(value) && value.every(nonEmptyString);
}

function present(value) {
  return value !== undefined && value !== null && value !== "";
}

function screenshotPath(value) {
  return nonEmptyString(value) && /\.png$/i.test(value);
}

function normalizedText(value) {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

function includesText(haystack, needle) {
  return normalizedText(haystack).toLocaleLowerCase().includes(
    normalizedText(needle).toLocaleLowerCase(),
  );
}

function nonNegativeInteger(value) {
  return Number.isInteger(value) && value >= 0;
}

function validTimestamp(value) {
  return nonEmptyString(value) && Number.isFinite(Date.parse(value));
}

export function screenshotPathMatchesId(id, value) {
  if (!nonEmptyString(id) || !screenshotPath(value)) return false;
  const escapedId = id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|[^a-z0-9])${escapedId}(?:[^a-z0-9]|$)`, "i").test(path.basename(value));
}

export function evidenceScreenshotReferences(entry) {
  if (entry?.schemaVersion === GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION && Array.isArray(entry.visualSteps)) {
    return entry.visualSteps
      .filter((step) => screenshotPath(step?.screenshot))
      .map((step) => ({ stage: step.stage, screenshot: step.screenshot }));
  }
  return screenshotPath(entry?.screenshot)
    ? [{ stage: "legacy-outcome", screenshot: entry.screenshot }]
    : [];
}

/**
 * Capture the DOM oracle and its PNG through one helper. The DOM state is read
 * immediately before the screenshot, after two animation frames, so required
 * and forbidden observations describe this capture rather than text collected
 * earlier or after a recovery action.
 */
export async function captureVisualStep(page, input) {
  const terminal = input.terminal === true;
  const requiredVisible = Array.isArray(input.requiredVisible) ? input.requiredVisible : [];
  const forbiddenVisible = [
    ...(Array.isArray(input.forbiddenVisible) ? input.forbiddenVisible : []),
    ...(terminal ? TERMINAL_FORBIDDEN_VISIBLE : []),
  ].filter((value, index, values) => nonEmptyString(value) && values.indexOf(value) === index);

  await page.evaluate(() => new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));

  const capture = await page.evaluate(() => {
    const visible = (element) => {
      if (!(element instanceof HTMLElement) && !(element instanceof SVGElement)) return false;
      const style = window.getComputedStyle(element);
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
      if (element.getAttribute("aria-hidden") === "true" || element.hasAttribute("hidden")) return false;
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    };
    const countVisible = (selector) => [...document.querySelectorAll(selector)].filter(visible).length;
    return {
      text: (document.body?.innerText || "").replace(/\s+/g, " ").trim(),
      ariaBusyCount: countVisible('[aria-busy="true"]'),
      skeletonCount: countVisible('[data-skeleton], [class*="skeleton" i], [class~="animate-pulse"]'),
      loadingIndicatorCount: countVisible('[data-loading="true"], [data-state="loading"], [aria-label*="loading" i], [class*="loading" i], [class~="animate-spin"]'),
    };
  });

  await page.screenshot({
    path: input.screenshot,
    fullPage: input.fullPage === true,
    animations: "disabled",
    caret: "initial",
  });

  return {
    id: input.id,
    stage: input.stage,
    terminal,
    screenshot: input.screenshot,
    capturedAt: new Date().toISOString(),
    url: page.url(),
    requiredVisible,
    forbiddenVisible,
    capture,
  };
}

/**
 * Build one auditable browser-path record. Supplying visualSteps opts an entry
 * into schema v2; IDs with a required stage contract are always v2. If one of
 * those callers cannot capture its state, it is recorded explicitly as
 * NOT_VISUALLY_PROVABLE with no steps and fails closed.
 */
export function makeGoldenPathEvidence(input) {
  const visualSteps = Array.isArray(input.visualSteps)
    ? input.visualSteps
    : REQUIRED_VISUAL_STAGES[input.id]?.length > 0
      ? []
      : null;
  const schemaVersion = visualSteps
    ? GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION
    : LEGACY_GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION;
  const screenshot = input.screenshot ?? visualSteps?.at(-1)?.screenshot;
  return {
    schemaVersion,
    id: input.id,
    mode: "browser",
    status: input.status,
    persona: input.persona,
    preconditions: input.preconditions,
    actions: input.actions,
    observed: input.observed,
    screenshot,
    ...(visualSteps
      ? {
          visualProof: visualSteps.length > 0
            ? input.visualProof ?? "PROVEN"
            : "NOT_VISUALLY_PROVABLE",
          visualSteps,
        }
      : {}),
    consoleErrors: input.consoleErrors,
    requestFailures: input.requestFailures,
    assertions: input.assertions,
  };
}

function failure(field, expected, actual) {
  return { field, expected, actual };
}

function validateVisualStep(id, step, index, failures) {
  const field = `visualSteps.${index}`;
  const check = (suffix, condition, expected, actual) => {
    if (!condition) failures.push(failure(`${field}.${suffix}`, expected, actual));
  };

  check("id", step?.id === id, id, step?.id);
  check("stage", nonEmptyString(step?.stage), "non-empty stage", step?.stage);
  check("terminal", typeof step?.terminal === "boolean", "boolean", step?.terminal);
  check("screenshot", screenshotPath(step?.screenshot), "PNG screenshot path", step?.screenshot);
  check("screenshot.id", screenshotPathMatchesId(id, step?.screenshot), `filename containing ${id}`, step?.screenshot);
  check("capturedAt", validTimestamp(step?.capturedAt), "ISO timestamp", step?.capturedAt);
  check("url", nonEmptyString(step?.url), "capture URL", step?.url);
  check("requiredVisible", nonEmptyStringArray(step?.requiredVisible), "one or more exact required strings", step?.requiredVisible);
  check("forbiddenVisible", stringArray(step?.forbiddenVisible), "array of forbidden strings", step?.forbiddenVisible);
  check("capture.text", nonEmptyString(step?.capture?.text), "same-moment DOM text", step?.capture?.text);
  for (const countField of ["ariaBusyCount", "skeletonCount", "loadingIndicatorCount"]) {
    check(`capture.${countField}`, nonNegativeInteger(step?.capture?.[countField]), "non-negative integer", step?.capture?.[countField]);
  }

  if (Array.isArray(step?.requiredVisible) && nonEmptyString(step?.capture?.text)) {
    step.requiredVisible.forEach((text, visibleIndex) => {
      check(`requiredVisible.${visibleIndex}.present`, includesText(step.capture.text, text), text, "not present at capture");
    });
  }
  if (Array.isArray(step?.forbiddenVisible) && nonEmptyString(step?.capture?.text)) {
    step.forbiddenVisible.forEach((text, visibleIndex) => {
      check(`forbiddenVisible.${visibleIndex}.absent`, !includesText(step.capture.text, text), `not ${text}`, "present at capture");
    });
  }

  if (step?.terminal === true) {
    for (const text of TERMINAL_FORBIDDEN_VISIBLE) {
      check(
        `terminal.forbiddenVisible.${text.toLocaleLowerCase()}`,
        Array.isArray(step.forbiddenVisible) && step.forbiddenVisible.some((value) => includesText(value, text)),
        `forbiddenVisible includes ${text}`,
        step.forbiddenVisible,
      );
    }
    check("terminal.computingOrLoading", !/\b(?:computing|loading)\b/i.test(step?.capture?.text || ""), "no COMPUTING/loading text", step?.capture?.text);
    check("terminal.ariaBusyCount", step?.capture?.ariaBusyCount === 0, 0, step?.capture?.ariaBusyCount);
    check("terminal.skeletonCount", step?.capture?.skeletonCount === 0, 0, step?.capture?.skeletonCount);
    check("terminal.loadingIndicatorCount", step?.capture?.loadingIndicatorCount === 0, 0, step?.capture?.loadingIndicatorCount);
  }
}

/**
 * Validate the common evidence envelope. ID-specific numerical, persistence,
 * authorization, and recovery invariants are layered on by the release gate.
 */
export function validateGoldenPathEvidence(id, entry) {
  const failures = [];
  const check = (field, condition, expected, actual) => {
    if (!condition) failures.push(failure(field, expected, actual));
  };
  const requiredStages = REQUIRED_VISUAL_STAGES[id] ?? [];
  const schemaVersion = entry?.schemaVersion;
  const supportedSchema = schemaVersion === LEGACY_GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION ||
    schemaVersion === GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION;

  check("schemaVersion", supportedSchema, "1 or 2", schemaVersion);
  if (requiredStages.length > 0) {
    check("schemaVersion", schemaVersion === GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION, String(GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION), schemaVersion);
  }
  check("id", entry?.id === id, id, entry?.id);
  check("mode", entry?.mode === "browser", "browser", entry?.mode);
  check("status", entry?.status === "PASS", "PASS", entry?.status);
  check("persona", nonEmptyString(entry?.persona), "non-empty persona", entry?.persona);
  check("preconditions", nonEmptyStringArray(entry?.preconditions), "one or more concrete preconditions", entry?.preconditions);
  check("actions", nonEmptyStringArray(entry?.actions), "one or more exact browser actions", entry?.actions);
  check("screenshot", screenshotPath(entry?.screenshot), "PNG screenshot path", entry?.screenshot);
  check("screenshot.id", screenshotPathMatchesId(id, entry?.screenshot), `filename containing ${id}`, entry?.screenshot);
  check("consoleErrors", Array.isArray(entry?.consoleErrors) && entry.consoleErrors.length === 0, "[]", entry?.consoleErrors);
  check("requestFailures", Array.isArray(entry?.requestFailures) && entry.requestFailures.length === 0, "[]", entry?.requestFailures);

  for (const field of REQUIRED_OBSERVED_FIELDS) {
    const value = entry?.observed?.[field];
    const valid = field === "visible" ? nonEmptyStringArray(value) : present(value);
    check(`observed.${field}`, valid, field === "visible" ? "one or more exact visible observations" : "explicit observed value or not-applicable marker", value);
  }

  if (schemaVersion === GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION) {
    check("visualProof", entry?.visualProof === "PROVEN", "PROVEN", entry?.visualProof);
    check("visualSteps", Array.isArray(entry?.visualSteps) && entry.visualSteps.length > 0, "one or more same-moment visual steps", entry?.visualSteps);
    if (Array.isArray(entry?.visualSteps)) {
      const stageNames = entry.visualSteps.map((step) => step?.stage);
      check("visualSteps.stages.unique", new Set(stageNames).size === stageNames.length, "unique stage names", stageNames);
      entry.visualSteps.forEach((step, index) => validateVisualStep(id, step, index, failures));
      check(
        "screenshot.visualStep",
        entry.visualSteps.some((step) => step?.screenshot === entry.screenshot),
        "top-level screenshot references one visual step",
        entry?.screenshot,
      );
      for (const stage of requiredStages) {
        const requiredStep = entry.visualSteps.find((step) => step?.stage === stage);
        check(`visualSteps.required.${stage}`, Boolean(requiredStep), stage, stageNames);
        check(`visualSteps.required.${stage}.terminal`, requiredStep?.terminal === true, true, requiredStep?.terminal);
        for (const requiredText of REQUIRED_VISUAL_STAGE_TEXT[id]?.[stage] ?? []) {
          check(
            `visualSteps.required.${stage}.text.${requiredText}`,
            Array.isArray(requiredStep?.requiredVisible) &&
              requiredStep.requiredVisible.some((value) => includesText(value, requiredText)),
            requiredText,
            requiredStep?.requiredVisible,
          );
        }
        for (const forbiddenText of REQUIRED_VISUAL_STAGE_FORBIDDEN_TEXT[id]?.[stage] ?? []) {
          check(
            `visualSteps.required.${stage}.forbidden.${forbiddenText}`,
            Array.isArray(requiredStep?.forbiddenVisible) &&
              requiredStep.forbiddenVisible.some((value) => includesText(value, forbiddenText)),
            forbiddenText,
            requiredStep?.forbiddenVisible,
          );
        }
      }
    }
  }

  const assertions = entry?.assertions;
  check("assertions", Array.isArray(assertions) && assertions.length > 0, "one or more field-level assertions", assertions);
  if (Array.isArray(assertions)) {
    assertions.forEach((assertion, index) => {
      check(`assertions.${index}.name`, nonEmptyString(assertion?.name), "non-empty assertion name", assertion?.name);
      check(`assertions.${index}.expected`, present(assertion?.expected), "explicit expected value", assertion?.expected);
      check(`assertions.${index}.actual`, present(assertion?.actual), "explicit actual value", assertion?.actual);
      check(`assertions.${index}.pass`, assertion?.pass === true, "true", assertion?.pass);
    });
  }

  return { id, valid: failures.length === 0, failures };
}

export function validateGoldenPathMap(requiredIds, goldenPaths) {
  const byId = Object.fromEntries(
    requiredIds.map((id) => [id, validateGoldenPathEvidence(id, goldenPaths?.[id])])
  );
  const problems = Object.values(byId).flatMap((item) =>
    item.failures.map((itemFailure) => ({ id: item.id, ...itemFailure }))
  );
  return {
    total: requiredIds.length,
    valid: Object.values(byId).filter((item) => item.valid).length,
    byId,
    problems,
  };
}
