"use client";

import { PageErrorBoundary } from "@/components/v4/moments/page-error-boundary";

export default function AppV4Error({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return <PageErrorBoundary error={error} retry={retry} />;
}
