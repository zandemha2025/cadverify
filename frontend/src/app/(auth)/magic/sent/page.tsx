import type { Metadata } from "next";
import Link from "next/link";
import { AuthFrame } from "@/components/auth/auth-frame";

export const metadata: Metadata = {
  title: "Magic link sent - ProofShape",
  robots: { index: false, follow: false },
};

export default function MagicSentPage() {
  return (
    <AuthFrame
      eyebrow="Magic link"
      title="Check your email."
      body="If that address is allowed to sign in, a single-use link is on its way."
    >
      <div style={{ display: "flex", justifyContent: "center", gap: 12, flexWrap: "wrap" }}>
        <Link href="/login" style={{ borderRadius: 999, padding: "11px 18px", background: "#f5f5f7", color: "#050506", textDecoration: "none", fontSize: 13, fontWeight: 500 }}>
          Try another email
        </Link>
      </div>
    </AuthFrame>
  );
}
