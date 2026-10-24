import { getHealthDeep } from "@/app/(app)/settings/organization/actions";
import { ActivityScreen } from "@/components/v4/account/activity-screen";

export const dynamic = "force-dynamic";

export default async function Page() {
  const health = await getHealthDeep();
  return <ActivityScreen health={{ ...health, checkedAt: new Date().toISOString() }} />;
}
