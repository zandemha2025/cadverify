"use server";
import { cookies } from "next/headers";
import { backendUrl } from "@/lib/api-base";

async function authed(path: string, init?: RequestInit) {
  const c = await cookies();
  const dash = c.get("dash_session")?.value ?? "";
  return fetch(backendUrl(path), {
    ...init,
    headers: { ...(init?.headers || {}), Cookie: `dash_session=${dash}` },
    cache: "no-store",
  });
}

export async function listKeys() {
  const r = await authed("/api/v1/keys");
  if (!r.ok) throw new Error("list failed");
  return r.json();
}
