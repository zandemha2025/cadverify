"use client";

/**
 * Where a check stops before an answer: out of checks (X3) and a file that can't
 * be read (X4). Both are the shared moments components; X3 reads the Pro price
 * from the same-origin /api/billing/plans. The phone check (X2) is the shared
 * PhoneGateView, mounted by the check page.
 */
import { OutOfChecks as SharedOutOfChecks } from "../moments";

export { CantReadSheet, CadToolSteps } from "../moments";

/** The shared X3 modal; it reads Pro's price from /api/billing/plans itself and keeps the refused file. */
export function OutOfChecks({ message, onClose, file }: { message: string; onClose?: () => void; file?: File | null }) {
  return <SharedOutOfChecks message={message} onClose={onClose} file={file} />;
}
