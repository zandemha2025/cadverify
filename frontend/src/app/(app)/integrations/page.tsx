import type { Metadata } from "next";
import { IntegrationsClient } from "./integrations-client";
import { getOrgContext } from "../settings/organization/actions";

export const metadata: Metadata = {
  title: "Integrations - ProofShape",
  robots: { index: false, follow: false },
};

export default async function IntegrationsPage() {
  const org = await getOrgContext();
  return <IntegrationsClient canManageCredentials={org?.role === "admin"} />;
}
