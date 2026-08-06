import type { Metadata } from "next";
import { IntegrationsClient } from "./integrations-client";

export const metadata: Metadata = {
  title: "Integrations - ProofShape",
  robots: { index: false, follow: false },
};

export default function IntegrationsPage() {
  return <IntegrationsClient />;
}
