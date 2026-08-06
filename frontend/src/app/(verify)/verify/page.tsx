import type { Metadata } from "next";
import { VerifyApp } from "@/components/verify/verify-app";
import { getSessionOrganizationAccess } from "@/lib/dal";

export const metadata: Metadata = {
  title: "Verify — ProofShape",
  description:
    "Can this part be made, on your machines, in materials that survive its world — and what will it really take?",
};

// The Verify shell is a client-only instrument (WebGL stage, live engine calls).
export const dynamic = "force-dynamic";

export default async function VerifyPage() {
  const organizationAccess = await getSessionOrganizationAccess();
  return <VerifyApp organizationAccess={organizationAccess} />;
}
