import type { Metadata } from "next";
import Link from "next/link";
import { AuthFrame } from "@/components/auth/auth-frame";

export const metadata: Metadata = {
  title: "Magic link sent - CadVerify",
  robots: { index: false, follow: false },
};

export default async function MagicSentPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string }>;
}) {
  const { email } = await searchParams;
  return (
    <AuthFrame
      eyebrow="Magic link"
      title="Check your email."
      body={
        email
          ? `If ${email} is allowed to sign in, a single-use link is on its way.`
          : "If that address is allowed to sign in, a single-use link is on its way."
      }
    >
      <div style={{ display: "flex", justifyContent: "center", gap: 12, flexWrap: "wrap" }}>
        <Link href="/login" style={{ border: "1px solid rgba(245,245,247,0.18)", borderRadius: 999, padding: "11px 18px", color: "#f5f5f7", textDecoration: "none", fontSize: 13 }}>
          Back to login
        </Link>
        <Link href="/signup" style={{ borderRadius: 999, padding: "11px 18px", background: "#f5f5f7", color: "#050506", textDecoration: "none", fontSize: 13, fontWeight: 500 }}>
          Try another email
        </Link>
      </div>
    </AuthFrame>
  );
}
