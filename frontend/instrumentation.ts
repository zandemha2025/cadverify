/**
 * Server-side Sentry wiring (Next.js `instrumentation.ts` convention).
 *
 * `sentry.server.config.ts` only defines `Sentry.init(...)` — Next.js does not
 * load it automatically unless something imports it from `register()` here.
 * (The browser side is different: `instrumentation-client.ts` IS a native
 * Next.js convention that Next loads itself, no wiring needed.)
 *
 * This app has no edge runtime (no `runtime = "edge"` route/proxy config —
 * `src/proxy.ts` defaults to the Node.js runtime per Next's Proxy docs), so
 * only the nodejs branch is wired; there is no `sentry.edge.config.ts`.
 *
 * `Sentry.init` itself is DSN-gated (`enabled: !!NEXT_PUBLIC_SENTRY_DSN` in
 * sentry.server.config.ts), so this file is a no-op end-to-end whenever
 * NEXT_PUBLIC_SENTRY_DSN is unset — dev/test/local builds are unaffected.
 */
const DEV_RELEASES = new Set(["", "dev", "development", "local", "test", "ci"]);

function assertProductionRuntimeConfig() {
  const release = (process.env.RELEASE || "dev").trim().toLowerCase();
  if (DEV_RELEASES.has(release)) return;

  if (process.env.PRODUCTION_AUTH_PROXY_REQUIRED === "1") {
    const raw = (process.env.AUTH_PROXY_SECRET || "").trim();
    const decoded = Buffer.from(raw, "base64");
    if (
      !raw ||
      !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(raw) ||
      decoded.length < 32 ||
      decoded.toString("base64") !== raw
    ) {
      throw new Error(
        "AUTH_PROXY_SECRET must be canonical base64 for at least 32 bytes",
      );
    }
  }

  if (process.env.MAGIC_LINK_UI_ENABLED === "1") {
    const siteKey = (process.env.TURNSTILE_SITE_KEY || "").trim();
    if (siteKey.length < 10 || /\s/.test(siteKey)) {
      throw new Error("TURNSTILE_SITE_KEY is required when magic-link UI is enabled");
    }
  }

  if (
    process.env.PRODUCTION_VERIFIED_SIGNUP_REQUIRED === "1" &&
    process.env.PUBLIC_PASSWORD_SIGNUP_ENABLED !== "0"
  ) {
    throw new Error(
      "PUBLIC_PASSWORD_SIGNUP_ENABLED must be 0 when verified signup is required",
    );
  }

  const authMode = (process.env.AUTH_MODE || "password").trim().toLowerCase();
  if (new Set(["saml", "oidc", "hybrid"]).has(authMode)) {
    const ssoPath = (process.env.SSO_LOGIN_PATH || "").trim();
    if (!/^\/auth\/(saml|oidc)\/login$/.test(ssoPath)) {
      throw new Error("SSO_LOGIN_PATH must select the configured SAML/OIDC login route");
    }
  }

  if (process.env.PRODUCTION_PUBLIC_API_TLS_REQUIRED !== "1") return;

  const deploymentEnvironment = (process.env.DEPLOYMENT_ENVIRONMENT || "").trim();
  if (!new Set(["saas-staging", "saas-production"]).has(deploymentEnvironment)) {
    throw new Error(
      "DEPLOYMENT_ENVIRONMENT must identify saas-staging or saas-production",
    );
  }

  const raw = (process.env.API_BASE || "").replace(/\\[rn]/g, "").trim();
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("API_BASE must be a valid HTTPS origin");
  }
  if (
    parsed.protocol !== "https:" ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash ||
    parsed.origin !== raw
  ) {
    throw new Error("API_BASE must be a canonical HTTPS origin");
  }
}

export async function register() {
  assertProductionRuntimeConfig();
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
}

export { captureRequestError as onRequestError } from "@sentry/nextjs";
