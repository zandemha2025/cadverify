export const GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION = 1;

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

function present(value) {
  return value !== undefined && value !== null && value !== "";
}

function screenshotPath(value) {
  return nonEmptyString(value) && /\.png$/i.test(value);
}

/**
 * Build one auditable browser-path record. Callers must supply observations
 * captured from the real browser/API/database journey; this helper deliberately
 * does not infer PASS from a step name or from the absence of an exception.
 */
export function makeGoldenPathEvidence(input) {
  return {
    schemaVersion: GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION,
    id: input.id,
    mode: "browser",
    status: input.status,
    persona: input.persona,
    preconditions: input.preconditions,
    actions: input.actions,
    observed: input.observed,
    screenshot: input.screenshot,
    consoleErrors: input.consoleErrors,
    requestFailures: input.requestFailures,
    assertions: input.assertions,
  };
}

function failure(field, expected, actual) {
  return { field, expected, actual };
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

  check("schemaVersion", entry?.schemaVersion === GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION, String(GOLDEN_PATH_EVIDENCE_SCHEMA_VERSION), entry?.schemaVersion);
  check("id", entry?.id === id, id, entry?.id);
  check("mode", entry?.mode === "browser", "browser", entry?.mode);
  check("status", entry?.status === "PASS", "PASS", entry?.status);
  check("persona", nonEmptyString(entry?.persona), "non-empty persona", entry?.persona);
  check("preconditions", nonEmptyStringArray(entry?.preconditions), "one or more concrete preconditions", entry?.preconditions);
  check("actions", nonEmptyStringArray(entry?.actions), "one or more exact browser actions", entry?.actions);
  check("screenshot", screenshotPath(entry?.screenshot), "PNG screenshot path", entry?.screenshot);
  check("consoleErrors", Array.isArray(entry?.consoleErrors) && entry.consoleErrors.length === 0, "[]", entry?.consoleErrors);
  check("requestFailures", Array.isArray(entry?.requestFailures) && entry.requestFailures.length === 0, "[]", entry?.requestFailures);

  for (const field of REQUIRED_OBSERVED_FIELDS) {
    const value = entry?.observed?.[field];
    const valid = field === "visible" ? nonEmptyStringArray(value) : present(value);
    check(`observed.${field}`, valid, field === "visible" ? "one or more exact visible observations" : "explicit observed value or not-applicable marker", value);
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
