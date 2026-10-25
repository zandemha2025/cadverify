import { getPlans } from "@/lib/plans";
import { BillingScreen } from "@/components/v4/account/billing-screen";

export const dynamic = "force-dynamic";

export default async function Page() {
  const plans = await getPlans();
  return <BillingScreen plans={plans} />;
}
