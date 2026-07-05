"use server";

import { redirect } from "next/navigation";
import { backendUrl } from "@/lib/api-base";

export async function startMagic(formData: FormData): Promise<void> {
  const email = String(formData.get("email") ?? "");
  const res = await fetch(backendUrl("/auth/magic/start"), {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as {
      detail?: { message?: string };
    };
    throw new Error(body?.detail?.message ?? "Magic link request failed");
  }
  redirect(`/magic/sent?email=${encodeURIComponent(email)}`);
}
