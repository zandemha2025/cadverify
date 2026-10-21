"use client";

/**
 * /app/notices: every banner and notice (board X11) in one place, so the set
 * can be reviewed and checked together. Counts, names and email come from the
 * signed-in account; file and design names are labelled examples. Actions that
 * need a running check (Retry upload, Retry cost, …) say so instead of acting.
 */
import * as React from "react";
import { useAuth } from "@/components/ui/auth-provider";
import { API_BASE } from "@/lib/api-base";
import { useShell } from "../shell";
import { World } from "../ui";
import {
  BusyBanner,
  CantReadBanner,
  CheckInterruptedBanner,
  CostBlockedBanner,
  CostFailedBanner,
  DesignImportBanner,
  FreeChecksUsedBanner,
  NoActiveOrgBanner,
  NotInOrgBanner,
  OrgErrorBanner,
  PageError,
  PreviewFailed,
  ProBanner,
  SignedOutBanner,
} from "./banners";
import { OutOfChecks, useUsage } from "./out-of-checks";
import { RatesChip } from "./rates-chip";
import { ToastStack, useToasts } from "./toasts";
import "./moments.css";

const EXAMPLE_FILE = "example-part.step";

type Org = { org_id: string; name: string; is_active?: boolean };

export function NoticesPage() {
  const { user } = useAuth();
  const { pickFile } = useShell();
  const usage = useUsage();
  const toasts = useToasts();
  const [gone, setGone] = React.useState<Record<string, boolean>>({});
  const [orgName, setOrgName] = React.useState<string | null>(null);
  const [x3, setX3] = React.useState(false);
  const [stack, setStack] = React.useState(() => sampleToasts());
  const hide = (k: string) => () => setGone((g) => ({ ...g, [k]: true }));
  const example = (what: string) => () => toasts.show(`Nothing to ${what} here. On a check, this ${what === "retry" ? "retries it" : "runs it again"}.`);

  React.useEffect(() => {
    let live = true;
    fetch(`${API_BASE}/orgs`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((b: { active_org_id?: string; organizations?: Org[] } | null) => {
        if (!live || !b) return;
        const list = b.organizations ?? [];
        setOrgName((list.find((o) => o.org_id === b.active_org_id) ?? list[0])?.name ?? null);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const spec = (cap: string, node: React.ReactNode) => (
    <div className="spec">
      {cap ? <p className="cap">{cap}</p> : null}
      {node}
    </div>
  );

  return (
    <World label="Banners and notices">
      <div className="mo-gal">
        <div className="ghd">
          <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap" }}>
            <h1 className="ptitle">Banners and notices</h1>
            <p className="pmeta">
              <span>Shown above the part or in the sheet</span>
              <span>× hides one</span>
              <span>File names are examples</span>
            </p>
          </div>
          <span style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <RatesChip />
            <button
              className="reset"
              type="button"
              onClick={() => {
                setGone({});
                setStack(sampleToasts());
              }}
            >
              Show all
            </button>
          </span>
        </div>
        <div className="cols">
          <div className="col">
            <h2>Before a check</h2>
            {gone.signin ? null : spec("Upload refused · session ended", <SignedOutBanner fileName={EXAMPLE_FILE} onDismiss={hide("signin")} />)}
            {gone.quota
              ? null
              : spec(
                  "Upload refused · free checks used · Email us replaces Upgrade if checkout is down",
                  <FreeChecksUsedBanner fileName={EXAMPLE_FILE} used={usage?.used} cap={usage?.cap} onUpgrade={() => setX3(true)} onDismiss={hide("quota")} />,
                )}
            {gone.busy ? null : spec("Upload refused · service busy · the file is kept for retry", <BusyBanner fileName={EXAMPLE_FILE} onRetry={example("retry")} onDismiss={hide("busy")} />)}
            {gone.unread ? null : spec("Upload refused · file can’t be read", <CantReadBanner fileName="example-part.sldprt" onChooseFile={pickFile} onDismiss={hide("unread")} />)}
            {spec("Opened from Design Studio · loading, done, bad link", <DesignImportBanner state="loading" name="example-bracket" revision={3} />)}
            {gone.dsdone ? null : spec("", <DesignImportBanner state="done" name="example-bracket" revision={3} onDismiss={hide("dsdone")} />)}
            {spec("", <DesignImportBanner state="error" />)}
          </div>

          <div className="col">
            <h2>During and after a check</h2>
            {spec("Check stopped before any result · in the sheet", <CheckInterruptedBanner onRetry={example("retry")} />)}
            {spec("Cost failed after the process checks · in the sheet", <CostFailedBanner onRetryCost={example("retry")} onRerun={example("rerun")} />)}
            {spec("Cost blocked by the check allowance · in the sheet", <CostBlockedBanner onUpgrade={() => setX3(true)} pro={usage?.plan === "pro"} />)}
            {gone.pro ? null : spec("Back from checkout", <ProBanner monthlyChecks={usage?.plan === "pro" ? usage.cap : null} email={user?.email} onDismiss={hide("pro")} />)}
            {spec("Part preview failed · on the stage, where the part would be", <PreviewFailed onRetry={example("retry")} onChooseFile={pickFile} />)}
            {spec(
              "Toasts · bottom center · 4 s · hover or focus pauses · × closes",
              <ToastStack
                inline
                items={stack}
                onClose={(id) => setStack((s) => s.filter((t) => t.id !== id))}
              />,
            )}
          </div>

          <div className="col">
            <h2>Workspace</h2>
            {spec("Organization check failed · shown instead of org data", <OrgErrorBanner onRetry={example("retry")} />)}
            {spec("Member, but no organization chosen", <NoActiveOrgBanner orgName={orgName} onRetry={example("retry")} />)}
            {spec("Not in any organization", <NotInOrgBanner email={user?.email} onRetry={example("retry")} />)}
            {spec("A page fails to load · Review usage only for allowance errors", <PageError message="Couldn’t load this page." onRetry={example("retry")} />)}
            {spec(
              "",
              <PageError
                name="page-error-quota"
                title="Couldn’t load usage"
                message="Verification allowance used up for now. Retry after the rolling allowance becomes available."
                onRetry={example("retry")}
              />,
            )}
          </div>
        </div>
      </div>
      {toasts.node}
      {x3 ? <OutOfChecks onClose={() => setX3(false)} /> : null}
    </World>
  );
}

function sampleToasts() {
  return [
    { id: -1, message: "Check complete · same file, same result every time", duration: 0 },
    { id: -2, message: `Removed ${EXAMPLE_FILE} from the example batch`, duration: 0, undo: () => {} },
    { id: -3, message: "Decision saved to the record", duration: 0 },
  ];
}
