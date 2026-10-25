import type { Metadata } from "next";
import { UI_V4 } from "@/lib/ui-v4-flag";
import { V4AuthLayout } from "@/components/v4/moments/auth-layout";
import "../(site)/site.css";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  if (UI_V4) return <V4AuthLayout>{children}</V4AuthLayout>;
  return <div className="cv-site">{children}</div>;
}
