import { headers } from "next/headers";
import { publicPasswordSignupEnabled } from "@/lib/public-signup";
import type { Metadata } from "next";
import { UI_V4 } from "@/lib/ui-v4-flag";
import { V4AuthLayout } from "@/components/v4/moments/auth-layout";
import "../(site)/site.css";
import { siteFonts } from "@/lib/site/fonts";
import { SiteSessionBoundary } from "@/components/site/site-session";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  const path = (await headers()).get("x-proofshape-request-path")?.split("?")[0];
  const marketingSignup = path === "/signup" && process.env.MAGIC_LINK_UI_ENABLED === "1" && !publicPasswordSignupEnabled(process.env.PUBLIC_PASSWORD_SIGNUP_ENABLED, process.env.RELEASE);
  if (UI_V4 && !marketingSignup) return <V4AuthLayout>{children}</V4AuthLayout>;
  return <SiteSessionBoundary><div className={`cv-site ${siteFonts}`}>{children}</div></SiteSessionBoundary>;
}
