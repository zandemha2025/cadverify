"use client";

/**
 * The v4 error boundary body (board X11, "A page fails to load"): the page's
 * message, its Error ID when the server gave one, Retry, and Review usage only
 * for allowance errors. Reports the error to Sentry like today's boundary.
 */
import * as React from "react";
import * as Sentry from "@sentry/nextjs";
import { World } from "../ui";
import { PageError } from "./banners";
import "./moments.css";

export function PageErrorBoundary({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  React.useEffect(() => {
    Sentry.captureException(error, { extra: { digest: error.digest, area: "app-v4" } });
  }, [error]);
  return (
    <World label="Something went wrong">
      <div className="mo-pagefail">
        <PageError message={error.message || "Couldn’t load this page."} digest={error.digest} onRetry={retry} />
      </div>
    </World>
  );
}
