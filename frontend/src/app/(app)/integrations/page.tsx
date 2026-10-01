import type { Metadata } from "next";
import { IntegrationsClient } from "./integrations-client";
import { getOrganizationAccess } from "../settings/organization/actions";
import { ErrorState } from "@/components/ui/error-state";

export const metadata: Metadata = {
  title: "Integrations - ProofShape",
  robots: { index: false, follow: false },
};

export default async function IntegrationsPage() {
  const access = await getOrganizationAccess();
  if (!access) return <ErrorState title="Organization access is unavailable" message="We couldn't confirm your active organization or permissions. Try again to reload integrations." retryHref="/integrations" />;
  const org = access.organizations.find((item) => item.orgId === access.activeOrgId);
  return <IntegrationsClient canManageCredentials={org?.role === "admin"} />;
}
