"use client";

import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";
import { Button } from "@/components/ui/button";

export default function AppError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error, {
      extra: { digest: error.digest, area: "app" },
    });
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
      <h2 className="text-xl font-semibold text-foreground">
        Something went wrong
      </h2>
      <p className="max-w-md text-muted-foreground">
        {error.message || "Something went wrong loading this page."}
      </p>
      {error.digest && (
        <p className="num text-xs text-muted-foreground">
          Error ID: {error.digest}
        </p>
      )}
      <Button className="mt-2" onClick={() => unstable_retry()}>
        Retry
      </Button>
    </div>
  );
}
