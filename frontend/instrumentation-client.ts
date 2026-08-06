import * as Sentry from "@sentry/nextjs";
import { scrubSentryEvent } from "@/lib/sentry-scrub";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN || "",
  tracesSampleRate: 0.1,
  replaysSessionSampleRate: 0,
  // CAD and auth screens are sensitive. Session replay stays disabled until a
  // separately reviewed masking/data-processing design is approved.
  replaysOnErrorSampleRate: 0,
  release: process.env.NEXT_PUBLIC_SENTRY_RELEASE || "dev",
  // Staging and production promote the same image. The release SHA remains
  // immutable while the runtime origin tag distinguishes deployments.
  environment: "commercial",
  initialScope:
    typeof window === "undefined"
      ? undefined
      : { tags: { deployment_origin: window.location.origin } },
  sendDefaultPii: false,
  beforeSend: scrubSentryEvent,
  enabled: !!process.env.NEXT_PUBLIC_SENTRY_DSN,
});
