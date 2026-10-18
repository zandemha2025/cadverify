import type { Metadata } from "next";
import { ResetPasswordForm } from "./reset-password-form";
import { UI_V4 } from "@/lib/ui-v4-flag";
import { V4ResetPassword } from "@/components/v4/moments/password-reset";

export const metadata: Metadata = { title: "Reset password — ScaleCad" };

export default function ResetPasswordPage() {
  if (UI_V4) return <V4ResetPassword />;
  return <ResetPasswordForm />;
}
