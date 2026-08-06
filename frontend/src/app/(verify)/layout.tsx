import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { VERIFY_UI } from "@/lib/verify-flag";
import { verifySession } from "@/lib/dal";
import { AuthProvider } from "@/components/ui/auth-provider";
import { AppShell } from "@/components/ui/app-shell";
import { TempoProvider } from "@/lib/tempo";
import { STAGE_UI } from "@/lib/stage-flag";
import "@fontsource-variable/instrument-sans";
import "@fontsource-variable/jetbrains-mono";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

/** Verify keeps its feature gate but shares the exact authenticated ProofShape
 * shell used by Design Studio and every other signed-in route. */
export default async function VerifyLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (!VERIFY_UI) notFound();
  const user = await verifySession();
  const tree = (
    <AuthProvider user={user}>
      <TempoProvider>
        <AppShell>{children}</AppShell>
      </TempoProvider>
    </AuthProvider>
  );
  return STAGE_UI ? (
    <div data-stage-type className="contents">
      {tree}
    </div>
  ) : (
    tree
  );
}
