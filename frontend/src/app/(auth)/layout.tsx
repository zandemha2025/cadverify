import type { Metadata } from "next";
import "../(site)/site.css";
import { siteFonts } from "@/lib/site/fonts";
import { SiteSessionBoundary } from "@/components/site/site-session";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <SiteSessionBoundary><div className={`cv-site ${siteFonts}`}>{children}</div></SiteSessionBoundary>;
}
