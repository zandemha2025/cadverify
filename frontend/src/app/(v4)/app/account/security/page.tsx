import { verifySession } from "@/lib/dal";
import { SecurityScreen } from "@/components/v4/account/security-screen";

export const dynamic = "force-dynamic";

export default async function Page() {
  const user = await verifySession();
  return (
    <SecurityScreen
      authMode={process.env.AUTH_MODE || "password"}
      magicLink={process.env.MAGIC_LINK_UI_ENABLED === "1"}
      hasPassword={user.has_password ?? user.auth_provider === "password"}
    />
  );
}
