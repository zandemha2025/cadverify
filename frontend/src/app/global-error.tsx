"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";
// global-error replaces the root layout, so pull in the design tokens directly
// (otherwise the primitive's token classes would resolve to nothing).
import "./globals.css";

export default function GlobalError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en">
      <body>
        <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
          <div className="text-center">
            <h2 className="mb-2 text-2xl font-bold text-foreground">
              Something went wrong
            </h2>
            <p className="mb-4 text-muted-foreground">
              An unexpected error occurred. Please try again.
            </p>
            <Button onClick={() => retry()}>Try again</Button>
          </div>
        </div>
      </body>
    </html>
  );
}
