"use server";
import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { backendUrl } from "@/lib/api-base";

const REVEAL_COOKIE = "cv_mint_once";
const REVEAL_PATH = "/settings/developer";

async function authed(path: string, init?: RequestInit) {
  const c = await cookies();
  const dash = c.get("dash_session")?.value ?? "";
  return fetch(backendUrl(path), {
    ...init,
    headers: { ...(init?.headers || {}), Cookie: `dash_session=${dash}` },
    cache: "no-store",
  });
}

async function preserveRevealCookie(r: Response) {
  const raw = r.headers.get("set-cookie") ?? "";
  const m = raw.match(/(?:^|,\s*)cv_mint_once=([^;]+)/);
  if (!m) return;

  const c = await cookies();
  c.set(REVEAL_COOKIE, decodeURIComponent(m[1]), {
    httpOnly: false,
    maxAge: 60,
    path: REVEAL_PATH,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });
}

export async function listKeys() {
  const r = await authed("/api/v1/keys");
  if (!r.ok) throw new Error("list failed");
  return r.json();
}

export async function createKey(name: string) {
  const r = await authed("/api/v1/keys", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
  await preserveRevealCookie(r);
  if (!r.ok) throw new Error("create failed");
  revalidatePath(REVEAL_PATH);
  return r.json();
}

export async function rotateKey(id: number) {
  const r = await authed(`/api/v1/keys/${id}/rotate`, { method: "POST" });
  await preserveRevealCookie(r);
  if (!r.ok) throw new Error("rotate failed");
  revalidatePath(REVEAL_PATH);
  return r.json();
}

export async function revokeKey(id: number) {
  const r = await authed(`/api/v1/keys/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("revoke failed");
  revalidatePath(REVEAL_PATH);
}

export async function renameKey(id: number, name: string) {
  const r = await authed(`/api/v1/keys/${id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) throw new Error("rename failed");
  revalidatePath(REVEAL_PATH);
}
