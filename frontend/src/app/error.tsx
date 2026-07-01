"use client";

import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";
import { Button } from "@/components/ui/button";

export default function RootError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error, {
      extra: { digest: error.digest },
    });
  }, [error]);

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 px-4 text-center">
      <h2 className="text-2xl font-semibold text-foreground">
        Something went wrong
      </h2>
      <p className="max-w-md text-muted-foreground">
        An unexpected error occurred. Our team has been notified.
      </p>
      {error.digest && (
        <p className="num text-xs text-muted-foreground">
          Error ID: {error.digest}
        </p>
      )}
      <Button className="mt-2" onClick={() => unstable_retry()}>
        Try again
      </Button>
    </div>
  );
}
