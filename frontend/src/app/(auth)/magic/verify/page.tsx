import { redirect } from "next/navigation";
import { backendUrl } from "@/lib/api-base";

export default async function MagicVerify({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  if (!token) redirect("/signup?err=missing");
  const res = await fetch(
    backendUrl(`/auth/magic/verify?token=${encodeURIComponent(token)}`),
    { redirect: "manual" },
  );
  if (res.status !== 303) redirect("/signup?err=invalid");
  const loc = res.headers.get("location") || "/keys";
  redirect(loc);
}
