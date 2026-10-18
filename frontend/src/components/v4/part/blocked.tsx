"use client";

/**
 * Where a check stops before an answer: out of checks (X3) and a file that can't
 * be read (X4). Both are the shared moments components; X3 gets the Pro price
 * from the same-origin /api/billing/plans. The phone check (X2) is the shared
 * PhoneGateView, mounted by the check page.
 */
import * as React from "react";
import { parsePlans, type Plans } from "@/lib/billing";
import { OutOfChecks as SharedOutOfChecks } from "../moments";

export { CantReadSheet, CadToolSteps } from "../moments";

/** The shared X3 modal, with the Pro price read from /api/billing/plans. */
export function OutOfChecks({ message, onClose }: { message: string; onClose?: () => void }) {
  const [plans, setPlans] = React.useState<Plans | null>(null);
  React.useEffect(() => {
    let live = true;
    fetch("/api/billing/plans", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => live && setPlans(b ? parsePlans(b) : null))
      .catch(() => live && setPlans(null));
    return () => {
      live = false;
    };
  }, []);
  return <SharedOutOfChecks message={message} onClose={onClose} plans={plans ?? undefined} />;
}
