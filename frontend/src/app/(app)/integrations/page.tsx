import type { Metadata } from "next";
import { IntegrationsClient } from "./integrations-client";

export const metadata: Metadata = {
  title: "Integrations - CadVerify",
  robots: { index: false, follow: false },
};

export default function IntegrationsPage() {
  return <IntegrationsClient />;
}
