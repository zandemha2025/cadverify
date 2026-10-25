import { OrgScreen } from "@/components/v4/account/org-screen";

export const dynamic = "force-dynamic";

export default function Page() {
  return <OrgScreen authMode={process.env.AUTH_MODE || "password"} magicLink={process.env.MAGIC_LINK_UI_ENABLED === "1"} />;
}
