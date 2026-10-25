import { SignupEmailForm } from "@/components/site/signup-email-form";
import { SiteShell } from "@/components/site/site-shell";
import { Suspense } from "react";
import { AuthFrame, AuthTextLink } from "@/components/auth/auth-frame";
import { publicPasswordSignupEnabled } from "@/lib/public-signup";
import { SignupForm } from "./signup-form";

export const dynamic = "force-dynamic";

export default function SignupPage() {
  const publicPasswordSignup = publicPasswordSignupEnabled(
    process.env.PUBLIC_PASSWORD_SIGNUP_ENABLED,
    process.env.RELEASE,
  );
  const magicEnabled = process.env.MAGIC_LINK_UI_ENABLED === "1";
  const ssoLoginPath = (process.env.SSO_LOGIN_PATH || "").trim();
  if (publicPasswordSignup) return <Suspense fallback={<p>Loading account form…</p>}><SignupForm /></Suspense>;

  if (!magicEnabled) {
    return (
      <AuthFrame
        eyebrow="Managed access"
        title="Contact your organization administrator"
        body="Accounts in this environment are provisioned through the approved identity provider."
        footer={<AuthTextLink href="/login">Back to login</AuthTextLink>}
      >
        {ssoLoginPath && (
          <a href={ssoLoginPath} style={{ display: "block", width: "100%", borderRadius: 999, background: "#f5f5f7", color: "#050506", padding: "13px 18px", textAlign: "center", textDecoration: "none", fontSize: 14, fontWeight: 500 }}>
            Continue with enterprise SSO
          </a>
        )}
      </AuthFrame>
    );
  }

  return <SiteShell><section className="cv-signup-page cv-wrap"><h1>Try ScaleCAD free.</h1><p>Enter your email and we’ll send you a link to sign in. No password needed. Then upload a part and see the answer.</p><SignupEmailForm /></section></SiteShell>;
}
