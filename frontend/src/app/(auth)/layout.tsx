import type { Metadata } from "next";
import "../(site)/site.css";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className="cv-site">{children}</div>;
}
