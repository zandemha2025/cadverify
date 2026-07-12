import Link from "next/link";
import { AuthFrame, AuthTextLink } from "@/components/auth/auth-frame";
import { SignupForm } from "./signup-form";

export const dynamic = "force-dynamic";

export default function SignupPage() {
  const signupOverride = process.env.PUBLIC_PASSWORD_SIGNUP_ENABLED;
  const release = (process.env.RELEASE || "dev").trim().toLowerCase();
  const released = !new Set(["", "dev", "development", "local", "test", "ci"]).has(release);
  const publicPasswordSignup = signupOverride
    ? signupOverride === "1"
    : !released;
  const magicEnabled = process.env.MAGIC_LINK_UI_ENABLED === "1";
  const ssoLoginPath = (process.env.SSO_LOGIN_PATH || "").trim();
  if (publicPasswordSignup) return <SignupForm />;

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

  return (
    <AuthFrame
      eyebrow="Verified access"
      title="Create your account securely"
      body="Production accounts begin with a single-use email link. After signing in, you can add a password in Settings → Security."
      footer={<>Already registered? <AuthTextLink href="/login">Log in</AuthTextLink></>}
    >
      <Link
        href="/login#magic-link"
        style={{ display: "block", width: "100%", borderRadius: 999, background: "#f5f5f7", color: "#050506", padding: "13px 18px", textAlign: "center", textDecoration: "none", fontSize: 14, fontWeight: 500 }}
      >
        Verify email and continue
      </Link>
    </AuthFrame>
  );
}
