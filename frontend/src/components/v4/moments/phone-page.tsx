"use client";

/**
 * /app/phone: verify a phone before the free checks start (board X2), with the
 * part waiting on the stage when there is one (held on the sign-in screen, or
 * handed over in memory). Once verified, "Open part" hands the part to Check a
 * part. When this account doesn't need a phone check, a waiting part goes
 * straight to the check.
 *
 * `?next=/app/...` sends "Continue" there instead (local paths only).
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { safeLocalPath } from "@/lib/safe-return-path";
import { setPendingFile } from "../pending-file";
import { R } from "../routes";
import { useShell } from "../shell";
import { Empty, Failed, World } from "../ui";
import { useHeldPart } from "./held-part";
import { PhoneGateView } from "./phone-gate";
import type { CheckUsage } from "./out-of-checks";
import "./moments.css";

export function PhonePage() {
  const router = useRouter();
  const { pickFile } = useShell();
  const held = useHeldPart();
  const [usage, setUsage] = React.useState<CheckUsage | null | "failed">(null);
  const [next, setNext] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    setNext(safeLocalPath(new URLSearchParams(window.location.search).get("next"), ""));
  }, []);

  React.useEffect(() => {
    let live = true;
    fetch("/api/auth/me/usage", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((u: CheckUsage) => live && setUsage(u))
      .catch(() => live && setUsage("failed"));
    return () => {
      live = false;
    };
  }, [attempt]);

  const required = usage && usage !== "failed" ? usage.phone_verification_required === true : null;
  const file = held.file;

  const openPart = React.useCallback(() => {
    if (file) {
      setPendingFile(file);
      router.push(R.check);
    } else if (next) router.push(next);
    else pickFile();
  }, [file, next, router, pickFile]);

  // No phone check needed: a waiting part goes straight to the check.
  React.useEffect(() => {
    if (required === false && held.ready && file) {
      setPendingFile(file);
      router.replace(R.check);
    }
  }, [required, held.ready, file, router]);

  if (usage === "failed")
    return (
      <World label="Verify your phone">
        <div className="mo-pagefail">
          <Failed title="Couldn’t read your account" detail="Your plan and phone status didn’t load. Nothing was changed." onRetry={() => setAttempt((n) => n + 1)} />
        </div>
      </World>
    );
  if (!usage || !held.ready || (required === false && file))
    return (
      <World label="Verify your phone">
        <div className="mo-pagefail" role="status">
          <span className="smeta">{file ? "Opening your part…" : "Loading…"}</span>
        </div>
      </World>
    );
  if (!required)
    return (
      <World label="Phone check">
        <div className="mo-pagefail">
          <div className="panel" style={{ width: "min(520px,100%)" }}>
            <Empty
              title="No phone check needed"
              actions={
                <>
                  <button className="btn ink sm" type="button" onClick={pickFile}>
                    Check a part
                  </button>
                  <Link className="btn sm" href={next || R.home}>
                    {next ? "Continue" : "Home"}
                  </Link>
                </>
              }
            >
              Your checks don&apos;t wait on a phone number: it&apos;s verified already, or your plan doesn&apos;t use one.
            </Empty>
          </div>
        </div>
      </World>
    );
  return (
    <PhoneGateView
      fileName={file?.name ?? null}
      onVerified={() => {}}
      onContinue={openPart}
      continueLabel={file ? "Open part" : next ? "Continue" : "Check a part"}
    />
  );
}
