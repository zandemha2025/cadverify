import type { Metadata } from "next";
import { SiteShell } from "@/components/site/site-shell";

export const metadata: Metadata = {
  title: "Terms - ProofShape",
  description: "ProofShape public service terms summary.",
};

export default function TermsPage() {
  return (
    <SiteShell>
      <article style={{ maxWidth: 820, margin: "0 auto", padding: "132px 24px 96px" }}>
        <p className="st-eyebrow">Terms</p>
        <h1 style={{ margin: "18px 0 34px", fontSize: "clamp(46px, 7vw, 92px)", fontWeight: 300, letterSpacing: "-0.06em", lineHeight: 0.94 }}>
          Use the verdict as evidence, not as blind authority.
        </h1>
        <div style={{ color: "rgba(255,255,255,0.70)", fontSize: 17, lineHeight: 1.75 }}>
          <p>
            ProofShape provides computational makeability and cost evidence. It does not replace engineering sign-off, supplier qualification, safety certification, export-control review, or a human decision.
          </p>
          <h2>Accounts</h2>
          <p>
            You are responsible for access to your account and organization. Invite links are single-use and must only be shared with the intended recipient.
          </p>
          <h2>Uploads</h2>
          <p>
            You must have the rights needed to upload CAD and related data. The service may reject files that are unsupported, unsafe to process, or outside configured limits.
          </p>
          <h2>Pilots and enterprise terms</h2>
          <p>
            Paid pilots and production deployments are governed by their signed order form, security exhibits, and data-processing terms.
          </p>
        </div>
      </article>
    </SiteShell>
  );
}
