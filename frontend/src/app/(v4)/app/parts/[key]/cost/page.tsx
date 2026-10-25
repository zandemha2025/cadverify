import { redirect } from "next/navigation";
import { R } from "@/components/v4/routes";

/** /app/parts/{key}/cost: the same cost breakdown, which lives beside the part at /app/part/{key}/cost. */
export default async function Page({ params, searchParams }: { params: Promise<{ key: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const [{ key }, sp] = await Promise.all([params, searchParams]);
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) for (const x of Array.isArray(v) ? v : v != null ? [v] : []) q.append(k, x);
  const qs = q.toString();
  redirect(`${R.cost(decodeURIComponent(key))}${qs ? `?${qs}` : ""}`);
}
