import type { Metadata } from "next";
import { headers } from "next/headers";
import { ForgotPasswordForm } from "./forgot-password-form";
import { UI_V4 } from "@/lib/ui-v4-flag";
import { V4ForgotPassword } from "@/components/v4/moments/password-reset";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Forgot password — ScaleCad" };

export default async function ForgotPasswordPage() {
  const authMode = (process.env.AUTH_MODE || "password").trim().toLowerCase();
  const passwordEnabled = authMode === "password" || authMode === "hybrid";
  const siteKey = passwordEnabled ? (process.env.TURNSTILE_SITE_KEY || "").trim() : "";
  if (UI_V4) return <V4ForgotPassword siteKey={siteKey} nonce={(await headers()).get("x-nonce") || undefined} />;
  return <ForgotPasswordForm siteKey={siteKey} nonce={(await headers()).get("x-nonce") || undefined} />;
}
