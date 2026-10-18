import { Suspense } from "react";
import { headers } from "next/headers";
import { LoginForm } from "./login-form";
import { getPlans } from "@/lib/plans";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const magicEnabled = process.env.MAGIC_LINK_UI_ENABLED === "1";
  const authMode = (process.env.AUTH_MODE || "password").trim().toLowerCase();
  const passwordEnabled = authMode === "password" || authMode === "hybrid";
  const ssoLoginPath = (process.env.SSO_LOGIN_PATH || "").trim() || undefined;
  const siteKey = magicEnabled
    ? (process.env.TURNSTILE_SITE_KEY || "").trim()
    : undefined;
  const nonce = (await headers()).get("x-nonce") || undefined;
  const { free } = await getPlans();
  return (
    <Suspense fallback={null}>
      <LoginForm
        turnstileSiteKey={siteKey || undefined}
        nonce={nonce}
        passwordEnabled={passwordEnabled}
        ssoLoginPath={ssoLoginPath}
        freeChecks={{ work: free.work_checks, personal: free.personal_checks }}
      />
    </Suspense>
  );
}
