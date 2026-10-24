import { redirect } from "next/navigation";
import { legacyWorkbenchTarget } from "@/components/v4/workbench/cost-url";
import { checkHref } from "@/components/v4/part/check-context";

/**
 * The cost breakdown's old address. A link with ?part= goes to that part's cost
 * breakdown (/app/part/{key}/cost) with every other parameter kept. Without a
 * part it was "cost a new file": that is Check a part now, the one way to add a
 * part (an old issue link keeps the problem it names).
 */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const issue = Array.isArray(sp.issue) ? sp.issue[0] : sp.issue;
  redirect(legacyWorkbenchTarget(sp) ?? checkHref({ issue }));
}
