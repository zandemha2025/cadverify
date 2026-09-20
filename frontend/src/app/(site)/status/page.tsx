import type { Metadata } from "next";
import { SiteShell } from "@/components/site/site-shell";
import styles from "./status.module.css";
import { backendUrl } from "@/lib/api-base";

export const metadata: Metadata = {
  title: "System status - ProofShape",
  description: "Live state of the ProofShape engine, worker, and web app.",
};

export const dynamic = "force-dynamic";

type State = "Operational" | "Degraded" | "Down";

type Health = {
  status?: "ok" | "degraded";
  build_id?: string;
  postgres?: boolean;
  redis?: boolean;
  async?: { worker?: "ok" | "unknown" | "unavailable" };
};

async function readHealth(): Promise<{ health: Health | null; checkedAt: string }> {
  const checkedAt = new Date().toISOString();
  try {
    const response = await fetch(backendUrl("/health"), {
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
    const health = (await response.json()) as Health;
    return { health, checkedAt };
  } catch {
    return { health: null, checkedAt };
  }
}

function stateColor(state: State): string {
  if (state === "Operational") return "#9CE8B4";
  if (state === "Degraded") return "#FFD17A";
  return "#FF8A7A";
}

export default async function StatusPage() {
  const { health, checkedAt } = await readHealth();
  const apiState: State = !health
    ? "Down"
    : health.status === "ok" && health.postgres
      ? "Operational"
      : "Degraded";
  const workerState: State = !health
    ? "Down"
    : health.redis && health.async?.worker === "ok"
      ? "Operational"
      : "Degraded";
  const rows: Array<[string, State, string]> = [
    ["Engine API", apiState, "Parses and grades your file"],
    ["Worker", workerState, "Runs batch and heavy jobs"],
    ["Web app", "Operational", "The app you are using"],
  ];

  return (
    <SiteShell>
      <section style={{ maxWidth: 960, margin: "0 auto", padding: "132px 24px 96px" }}>
        <p className="st-eyebrow">Status</p>
        <h1 style={{ margin: "18px 0 24px", fontSize: "clamp(50px, 8vw, 104px)", fontWeight: 300, letterSpacing: "-0.06em", lineHeight: 0.92 }}>
          System status
        </h1>
        <p style={{ maxWidth: 680, color: "rgba(255,255,255,0.68)", fontSize: 18, lineHeight: 1.6 }}>
          Live state of the ProofShape engine, worker, and web app.
        </p>

        <div style={{ marginTop: 48, borderBottom: "1px solid rgba(255,255,255,0.14)" }}>
          <div className={`${styles.statusGrid} ${styles.statusHeader}`} style={{ padding: "0 0 12px", color: "rgba(255,255,255,0.48)", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.1em" }}>
            <span>Component</span><span>State</span><span>What it does</span>
          </div>
          {rows.map(([component, state, job]) => (
            <div key={component} className={styles.statusGrid} style={{ alignItems: "center", padding: "20px 0", borderTop: "1px solid rgba(255,255,255,0.14)" }}>
              <strong style={{ fontWeight: 500 }}>{component}</strong>
              <span style={{ color: stateColor(state), display: "inline-flex", alignItems: "center", gap: 8 }}>
                <span aria-hidden style={{ width: 8, height: 8, borderRadius: 999, background: "currentColor" }} />
                {state}
              </span>
              <span className={styles.statusJob} style={{ color: "rgba(255,255,255,0.62)" }}>{job}</span>
            </div>
          ))}
        </div>

        <p style={{ marginTop: 18, fontFamily: "monospace", color: "rgba(255,255,255,0.58)", overflowWrap: "anywhere" }}>
          build {health?.build_id ?? "unavailable"} · checked {checkedAt}
        </p>

        <section style={{ marginTop: 72 }}>
          <p className="st-eyebrow">Incidents</p>
          <h2 style={{ margin: "14px 0 18px", fontSize: "clamp(32px, 5vw, 56px)", fontWeight: 300, letterSpacing: "-0.045em" }}>Incidents</h2>
          <p style={{ maxWidth: 700, color: "rgba(255,255,255,0.68)", fontSize: 18, lineHeight: 1.6 }}>
            No public incident feed is connected yet. Active incidents are communicated through deployment-specific support channels.
          </p>
        </section>

        <p style={{ marginTop: 72, paddingTop: 22, borderTop: "1px solid rgba(255,255,255,0.14)", color: "rgba(255,255,255,0.5)", lineHeight: 1.6 }}>
          Component states above come from the public health endpoint. Incident history will appear here when the incident feed is connected.
        </p>
      </section>
    </SiteShell>
  );
}
