"use server";

export async function startMagic(formData: FormData): Promise<void> {
  const res = await fetch(`${process.env.API_BASE}/auth/magic/start`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as {
      detail?: { message?: string };
    };
    throw new Error(body?.detail?.message ?? "Magic link request failed");
  }
}
