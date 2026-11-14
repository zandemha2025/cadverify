let verificationQueue: Promise<void> = Promise.resolve();

/** Serialize context writes and their dependent cost reads within one browser tab. */
export function serializeVerificationRun<T>(work: () => Promise<T>): Promise<T> {
  // ponytail: one tab-wide queue; split per mesh only if parallel upload throughput
  // becomes more important than deterministic part-context ordering.
  const run = verificationQueue.then(work, work);
  verificationQueue = run.then(() => undefined, () => undefined);
  return run;
}
