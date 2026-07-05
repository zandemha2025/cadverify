import type { Metadata } from "next";
import Link from "next/link";
import { SiteShell } from "@/components/site/site-shell";

export const metadata: Metadata = {
  title: "API Reference - CadVerify",
  description: "CadVerify developer API overview and reference links.",
};

export default function ApiReferencePage() {
  return (
    <SiteShell>
      <section style={{ maxWidth: 980, margin: "0 auto", padding: "132px 24px 96px" }}>
        <p className="st-eyebrow">Developer reference</p>
        <h1 style={{ margin: "18px 0 28px", fontSize: "clamp(52px, 8vw, 108px)", fontWeight: 300, letterSpacing: "-0.06em", lineHeight: 0.92 }}>
          One request, the whole verification record.
        </h1>
        <p style={{ maxWidth: 700, color: "rgba(255,255,255,0.68)", fontSize: 18, lineHeight: 1.6 }}>
          The interactive OpenAPI console remains the source of truth. This page exists so the public site has a durable developer doorway.
        </p>
        <div style={{ marginTop: 36, display: "flex", flexWrap: "wrap", gap: 12 }}>
          <Link href="/scalar" className="st-pill st-pill-solid">Open API console</Link>
          <Link href="/developers" className="st-pill">Developer overview</Link>
        </div>
        <pre style={{ marginTop: 44, overflowX: "auto", border: "1px solid rgba(255,255,255,0.14)", borderRadius: 18, padding: 24, color: "rgba(255,255,255,0.72)", background: "rgba(255,255,255,0.04)" }}>{`POST /api/v1/validate
POST /api/v1/validate/cost
GET  /api/v1/cost-decisions
GET  /api/v1/catalog

Authorization: Bearer <api-key>
Content-Type: multipart/form-data`}</pre>
      </section>
    </SiteShell>
  );
}
