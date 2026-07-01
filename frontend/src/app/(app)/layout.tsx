import { AppShell } from "@/components/ui/app-shell";
import { AuthProvider } from "@/components/ui/auth-provider";
import { verifySession } from "@/lib/dal";

/**
 * The single enterprise shell wrapping every authed surface. This is a SERVER
 * component: `verifySession()` validates the session against the backend and
 * redirects to /login when it is missing/invalid — the authoritative gate for
 * the entire platform. The resolved user is handed to the client AuthProvider.
 */
export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await verifySession();
  return (
    <AuthProvider user={user}>
      <AppShell>{children}</AppShell>
    </AuthProvider>
  );
}
