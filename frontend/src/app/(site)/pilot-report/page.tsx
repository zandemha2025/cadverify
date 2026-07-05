import type { Metadata } from "next";
import Link from "next/link";
import { SiteShell } from "@/components/site/site-shell";

export const metadata: Metadata = {
  title: "Pilot Report - CadVerify",
  description: "The CadVerify pilot report artifact shape.",
};

const SECTIONS = [
  ["Held-out accuracy", "Residuals on the parts the model did not tune on, including misses."],
  ["Floor declaration", "Machines, rates, materials, and assumptions used by every verdict."],
  ["Decision ledger", "The make/buy/acquire choices your team recorded, with provenance."],
  ["Next actions", "Capability gaps, supplier questions, and validation work still open."],
];

export default function PilotReportPage() {
  return (
    <SiteShell>
      <section style={{ maxWidth: 1040, margin: "0 auto", padding: "132px 24px 96px" }}>
        <p className="st-eyebrow">Pilot artifact</p>
        <h1 style={{ margin: "18px 0 28px", fontSize: "clamp(52px, 8vw, 108px)", fontWeight: 300, letterSpacing: "-0.06em", lineHeight: 0.92 }}>
          The closeout is a report your team can argue with.
        </h1>
        <p style={{ maxWidth: 720, color: "rgba(255,255,255,0.68)", fontSize: 18, lineHeight: 1.6 }}>
          A pilot report is not a marketing PDF. It is the measured record: where CadVerify matched your actuals, where it missed, and what data would improve the next pass.
        </p>
        <div style={{ marginTop: 46, display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          {SECTIONS.map(([title, body], i) => (
            <div key={title} style={{ border: "1px solid rgba(255,255,255,0.14)", borderRadius: 18, padding: 22, background: "rgba(255,255,255,0.04)" }}>
              <p style={{ margin: 0, color: "rgba(255,255,255,0.44)", fontFamily: "var(--st-mono)", fontSize: 12 }}>0{i + 1}</p>
              <h2 style={{ margin: "18px 0 10px", fontSize: 24, fontWeight: 300 }}>{title}</h2>
              <p style={{ margin: 0, color: "rgba(255,255,255,0.62)", lineHeight: 1.55 }}>{body}</p>
            </div>
          ))}
        </div>
        <p style={{ marginTop: 42 }}>
          <Link href="/company#pilot" className="st-pill st-pill-solid">Request a pilot</Link>
        </p>
      </section>
    </SiteShell>
  );
}
