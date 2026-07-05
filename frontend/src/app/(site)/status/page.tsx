import type { Metadata } from "next";
import { SiteShell } from "@/components/site/site-shell";

export const metadata: Metadata = {
  title: "Status - CadVerify",
  description: "CadVerify public status page.",
};

export default function StatusPage() {
  return (
    <SiteShell>
      <section style={{ maxWidth: 960, margin: "0 auto", padding: "132px 24px 96px" }}>
        <p className="st-eyebrow">Status</p>
        <h1 style={{ margin: "18px 0 28px", fontSize: "clamp(50px, 8vw, 104px)", fontWeight: 300, letterSpacing: "-0.06em", lineHeight: 0.92 }}>
          Public incident feed is not live yet.
        </h1>
        <p style={{ maxWidth: 680, color: "rgba(255,255,255,0.68)", fontSize: 18, lineHeight: 1.6 }}>
          CadVerify does not show synthetic uptime. Pilot customers receive deployment-specific support channels and incident communication. A public automated feed will appear here when it is wired to production monitoring.
        </p>
        <div style={{ marginTop: 42, display: "grid", gap: 14 }}>
          {[
            ["Hosted app", "No public metric feed yet"],
            ["API", "No public metric feed yet"],
            ["Workers", "No public metric feed yet"],
          ].map(([label, value]) => (
            <div key={label} style={{ display: "flex", justifyContent: "space-between", gap: 20, padding: "18px 0", borderTop: "1px solid rgba(255,255,255,0.14)" }}>
              <span>{label}</span>
              <span style={{ color: "rgba(255,255,255,0.56)" }}>{value}</span>
            </div>
          ))}
        </div>
      </section>
    </SiteShell>
  );
}
