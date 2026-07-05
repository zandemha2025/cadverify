import type { Metadata } from "next";
import Link from "next/link";
import { SiteShell } from "@/components/site/site-shell";

export const metadata: Metadata = {
  title: "Privacy - CadVerify",
  description: "How CadVerify handles CAD, account, pilot, and usage data.",
};

export default function PrivacyPage() {
  return (
    <SiteShell>
      <LegalArticle eyebrow="Privacy" title="CAD stays treated like crown-jewel data.">
        <p>
          CadVerify processes uploaded files to create verification records: geometry measurements, manufacturability findings, cost drivers, provenance, and user decisions. The product is built to keep the audit record, not to republish your CAD.
        </p>
        <h2>What we collect</h2>
        <p>
          Account details, authentication events, uploaded files, generated reports, machine/rate declarations, pilot correspondence, and operational telemetry needed to run and secure the service.
        </p>
        <h2>How it is used</h2>
        <p>
          To authenticate users, compute and store verification records, support pilots, diagnose incidents, prevent abuse, and improve the engine when you have agreed to that use.
        </p>
        <h2>Retention and deletion</h2>
        <p>
          Pilot and customer retention terms are governed by the applicable agreement. For privacy requests, contact <a href="mailto:security@cadverify.com">security@cadverify.com</a>.
        </p>
      </LegalArticle>
    </SiteShell>
  );
}

function LegalArticle({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <article style={{ maxWidth: 820, margin: "0 auto", padding: "132px 24px 96px" }}>
      <p className="st-eyebrow">{eyebrow}</p>
      <h1 style={{ margin: "18px 0 34px", fontSize: "clamp(46px, 7vw, 92px)", fontWeight: 300, letterSpacing: "-0.06em", lineHeight: 0.94 }}>
        {title}
      </h1>
      <div style={{ color: "rgba(255,255,255,0.70)", fontSize: 17, lineHeight: 1.75 }}>
        {children}
        <p style={{ marginTop: 34 }}>
          <Link href="/company#pilot" className="st-pill">Talk to CadVerify</Link>
        </p>
      </div>
    </article>
  );
}
