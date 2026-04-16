"use client";

import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";

export default function DashboardError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error, {
      extra: { digest: error.digest, area: "dashboard" },
    });
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
      <h2 className="text-xl font-semibold text-gray-900">
        Dashboard error
      </h2>
      <p className="max-w-md text-gray-600">
        {error.message || "Something went wrong loading the dashboard."}
      </p>
      {error.digest && (
        <p className="text-xs text-gray-400">
          Error ID: {error.digest}
        </p>
      )}
      <button
        onClick={() => unstable_retry()}
        className="mt-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
      >
        Retry
      </button>
    </div>
  );
}
