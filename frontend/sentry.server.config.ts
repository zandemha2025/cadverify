import * as Sentry from "@sentry/nextjs";
import { scrubSentryEvent } from "@/lib/sentry-scrub";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN || "",
  tracesSampleRate: 0.1,
  release: process.env.RELEASE || process.env.NEXT_PUBLIC_SENTRY_RELEASE || "dev",
  environment: process.env.DEPLOYMENT_ENVIRONMENT || process.env.NODE_ENV,
  sendDefaultPii: false,
  beforeSend: scrubSentryEvent,
  enabled: !!process.env.NEXT_PUBLIC_SENTRY_DSN,
});
