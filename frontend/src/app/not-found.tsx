import Link from "next/link";
import { SiteShell } from "@/components/site/site-shell";

export default function NotFound() {
  return (
    <SiteShell>
      <section style={{ minHeight: "72vh", display: "grid", placeItems: "center", padding: "120px 24px" }}>
        <div style={{ maxWidth: 760, textAlign: "center" }}>
          <p className="st-eyebrow">404</p>
          <h1 style={{ margin: "18px 0", fontSize: "clamp(52px, 9vw, 108px)", fontWeight: 300, letterSpacing: "-0.06em", lineHeight: 0.92 }}>
            That record is not here.
          </h1>
          <p style={{ margin: "0 auto 28px", maxWidth: 560, color: "rgba(255,255,255,0.62)", fontSize: 18, lineHeight: 1.55 }}>
            The link may be private, expired, or not issued yet. Public pages stay visible; product records stay behind the session gate.
          </p>
          <Link href="/" className="st-pill st-pill-solid">Back to CadVerify</Link>
        </div>
      </section>
    </SiteShell>
  );
}
