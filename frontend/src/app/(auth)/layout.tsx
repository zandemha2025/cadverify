import type { Metadata } from "next";
import "../(site)/site-theater.css";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="site-theater" style={{ flex: "1 1 auto", display: "flex", flexDirection: "column" }}>
      {children}
    </div>
  );
}
