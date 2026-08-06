export interface ReconstructionAttempt {
  files: File[];
  submissionId: string;
}

/** Reuse one ID only while retrying the exact same browser File objects. */
export function reconstructionAttempt(
  previous: ReconstructionAttempt | null,
  files: File[],
  makeSubmissionId: () => string,
): ReconstructionAttempt {
  const sameFiles =
    previous?.files.length === files.length &&
    previous.files.every((file, index) => file === files[index]);
  if (previous && sameFiles) return previous;
  return { files: [...files], submissionId: makeSubmissionId() };
}
