import { Suspense } from "react";
import { headers } from "next/headers";
import { LoginForm } from "./login-form";
import { getPlans } from "@/lib/plans";
import { UI_V4 } from "@/lib/ui-v4-flag";
import { publicPasswordSignupEnabled } from "@/lib/public-signup";
import { V4SignIn } from "@/components/v4/moments/sign-in";

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
  if (UI_V4) {
    return (
      <Suspense fallback={null}>
        <V4SignIn
          turnstileSiteKey={siteKey || undefined}
          nonce={nonce}
          passwordEnabled={passwordEnabled}
          ssoLoginPath={ssoLoginPath}
          freeChecks={{ work: free.work_checks, personal: free.personal_checks }}
          passwordSignup={publicPasswordSignupEnabled(process.env.PUBLIC_PASSWORD_SIGNUP_ENABLED, process.env.RELEASE)}
        />
      </Suspense>
    );
  }
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
