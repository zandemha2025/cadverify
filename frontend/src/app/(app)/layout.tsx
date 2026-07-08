import type { Metadata } from "next";
import { AppShell } from "@/components/ui/app-shell";
import { AuthProvider } from "@/components/ui/auth-provider";
import { TempoProvider } from "@/lib/tempo";
import { STAGE_UI } from "@/lib/stage-flag";
import { verifySession } from "@/lib/dal";
// Self-hosted variable faces — APP SCOPE ONLY (imported here, never in the root
// or marketing layout). These register the `@font-face`s used by the D5 stage
// typography ([data-stage-type] in globals.css); flag-off they load but stay
// unreferenced, so the rendered UI is unchanged.
import "@fontsource-variable/instrument-sans";
import "@fontsource-variable/jetbrains-mono";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

/**
 * The single enterprise shell wrapping every authed surface. This is a SERVER
 * component: `verifySession()` validates the session against the backend and
 * redirects to /login when it is missing/invalid — the authoritative gate for
 * the entire platform. The resolved user is handed to the client AuthProvider.
 *
 * `TempoProvider` wraps the shell (context only, no DOM) so any authed surface
 * can `useTempo()`. When the stage flag is on, a `display:contents` wrapper
 * carries `data-stage-type`, scoping the Instrument/JetBrains font swap to the
 * app (marketing keeps Geist). Flag-off, that wrapper is not rendered, so the
 * tree is byte-identical to today.
 */
export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
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
