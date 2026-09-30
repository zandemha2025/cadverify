"use client";

import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";
import { Button } from "@/components/ui/button";

export default function RootError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error, {
      extra: { digest: error.digest },
    });
  }, [error]);

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 px-4 text-center">
      <h2 className="text-2xl font-semibold text-foreground">
        Page temporarily unavailable
      </h2>
      <p className="max-w-md text-muted-foreground">
        We couldn&apos;t load this page. The service may be temporarily unavailable.
        Try again in a moment.
      </p>
      {error.digest && (
        <p className="num text-xs text-muted-foreground">
          Error ID: {error.digest}
        </p>
      )}
      <Button className="mt-2" onClick={() => retry()}>
        Try again
      </Button>
    </div>
  );
}
