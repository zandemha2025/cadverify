import { notFound } from "next/navigation";
import { VERIFY_UI } from "@/lib/verify-flag";
import { verifySession } from "@/lib/dal";

/**
 * The product Verify surface's own shell — a SEPARATE route group from `(app)`
 * so it does NOT inherit the dark enterprise AppShell (this surface is the
 * founder-approved light instrument with its own rail + top bar).
 *
 * Gate: flag-off → `notFound()` before anything renders, so the surface is
 * unreachable and the rest of the app is byte-identical. Flag-on → the same hard
 * session gate the rest of the platform uses (`verifySession()` redirects to
 * /login when the session is missing/invalid).
 */
export default async function VerifyLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (!VERIFY_UI) notFound();
  await verifySession();
  return children;
}
