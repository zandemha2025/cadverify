"use server";
import { cookies } from "next/headers";

async function authed(path: string, init?: RequestInit) {
  const c = await cookies();
  const dash = c.get("dash_session")?.value ?? "";
  return fetch(`${process.env.API_BASE}${path}`, {
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

export async function createKey(name: string) {
  const r = await authed("/api/v1/keys", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return r.json();
}

export async function rotateKey(id: number) {
  const r = await authed(`/api/v1/keys/${id}/rotate`, { method: "POST" });
  return r.json();
}

export async function revokeKey(id: number) {
  await authed(`/api/v1/keys/${id}`, { method: "DELETE" });
}

export async function renameKey(id: number, name: string) {
  await authed(`/api/v1/keys/${id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
}
