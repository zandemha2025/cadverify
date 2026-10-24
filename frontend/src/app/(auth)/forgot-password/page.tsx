import type { Metadata } from "next";
import { headers } from "next/headers";
import { ForgotPasswordForm } from "./forgot-password-form";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Forgot password — ScaleCad" };

export default async function ForgotPasswordPage() {
  const authMode = (process.env.AUTH_MODE || "password").trim().toLowerCase();
  const passwordEnabled = authMode === "password" || authMode === "hybrid";
  const siteKey = passwordEnabled ? (process.env.TURNSTILE_SITE_KEY || "").trim() : "";
  return <ForgotPasswordForm siteKey={siteKey} nonce={(await headers()).get("x-nonce") || undefined} />;
}
