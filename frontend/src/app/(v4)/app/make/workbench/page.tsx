import { Suspense } from "react";
import { redirect } from "next/navigation";
import { Workbench } from "@/components/v4/workbench/workbench";
import { legacyWorkbenchTarget } from "@/components/v4/workbench/cost-url";

/**
 * The cost breakdown's old address. A link with ?part= goes to that part's cost
 * breakdown (/app/part/{key}/cost) with every other parameter kept.
 */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const target = legacyWorkbenchTarget(await searchParams);
  if (target) redirect(target);
  return (
    <Suspense fallback={null}>
      <Workbench part={null} />
    </Suspense>
  );
}
