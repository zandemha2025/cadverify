import { getSsoStatus } from "@/app/(app)/settings/organization/actions";
import { SsoScreen } from "@/components/v4/account/sso-screen";

export const dynamic = "force-dynamic";

export default async function Page() {
  const sso = await getSsoStatus();
  return <SsoScreen sso={sso} authMode={process.env.AUTH_MODE || "password"} magicLink={process.env.MAGIC_LINK_UI_ENABLED === "1"} />;
}
