import type { Metadata } from "next";
import { SiteShell } from "@/components/site/site-shell";

export const metadata: Metadata = {
  title: "Data Processing Addendum - ProofShape",
  description: "ProofShape DPA availability and subprocessors summary.",
};

export default function DpaPage() {
  return (
    <SiteShell>
      <article style={{ maxWidth: 820, margin: "0 auto", padding: "132px 24px 96px" }}>
        <p className="st-eyebrow">DPA</p>
        <h1 style={{ margin: "18px 0 34px", fontSize: "clamp(46px, 7vw, 92px)", fontWeight: 300, letterSpacing: "-0.06em", lineHeight: 0.94 }}>
          Data terms travel with the pilot.
        </h1>
        <div style={{ color: "rgba(255,255,255,0.70)", fontSize: 17, lineHeight: 1.75 }}>
          <p>
            A data-processing addendum is available for pilots and enterprise deployments. It covers processing purpose, confidentiality, assistance with data-subject requests, deletion/return, and subprocessor notice.
          </p>
          <h2>Subprocessors</h2>
          <p>
            The exact list depends on deployment model. Hosted pilots may use cloud infrastructure, email delivery, observability, and support tooling. Self-hosted deployments can remove most hosted subprocessors.
          </p>
          <h2>Security review</h2>
          <p>
            Security questionnaires, architecture notes, and deployment boundaries are handled through the pilot intake. A dedicated ProofShape security address must be published before public launch.
          </p>
        </div>
      </article>
    </SiteShell>
  );
}
