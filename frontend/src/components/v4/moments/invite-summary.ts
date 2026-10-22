/**
 * What an invite link is for, read before sign-in (POST /api/auth/invite):
 * the organization, the role, who sent it, the invited address and when it
 * expires. The invite landing page names these, and sign-up from an invite
 * prefills and locks the address. Pure helpers here unit-test under node --test.
 */
export type InviteSummary = {
  org_name: string | null;
  role: string;
  email: string;
  invited_by: string | null;
  invited_by_name: string | null;
  expires_at: string | null;
};

export type SummaryResult = { ok: true; summary: InviteSummary } | { ok: false; status: number; message: string };

export async function fetchInviteSummary(token: string, f: typeof fetch = fetch): Promise<SummaryResult> {
  try {
    const res = await f("/api/auth/invite", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token }) });
    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (res.ok && typeof data.email === "string" && typeof data.role === "string") {
      return {
        ok: true,
        summary: {
          org_name: typeof data.org_name === "string" ? data.org_name : null,
          role: data.role,
          email: data.email,
          invited_by: typeof data.invited_by === "string" ? data.invited_by : null,
          invited_by_name: typeof data.invited_by_name === "string" ? data.invited_by_name : null,
          expires_at: typeof data.expires_at === "string" ? data.expires_at : null,
        },
      };
    }
    const d = data.detail as { message?: unknown } | string | undefined;
    const message = typeof d === "string" ? d : typeof d?.message === "string" ? d.message : "This invitation could not be checked.";
    return { ok: false, status: res.status, message };
  } catch {
    return { ok: false, status: 503, message: "Could not reach ScaleCAD." };
  }
}

/** "Invited by Sam Okafor (sam@kestrel.com)", or by the address alone. */
export function inviterLine(s: Pick<InviteSummary, "invited_by" | "invited_by_name">): string | null {
  if (s.invited_by_name && s.invited_by) return `Invited by ${s.invited_by_name} (${s.invited_by})`;
  if (s.invited_by) return `Invited by ${s.invited_by}`;
  return s.invited_by_name ? `Invited by ${s.invited_by_name}` : null;
}

export function roleWord(r: string | null | undefined): string {
  const v = (r ?? "member").trim() || "member";
  return v[0].toUpperCase() + v.slice(1);
}

/** What the role means once joined, in one line. */
export function roleMeans(role: string, org: string): string {
  if (role === "viewer") return `You’ll open ${org}’s parts and records. Viewers don’t check or change parts.`;
  if (role === "admin") return `You’ll check parts with ${org}’s machines and rates, and manage its members.`;
  return `You’ll check parts with ${org}’s machines and rates.`;
}

/** The invite token in a sign-up link: `?invite=`, or the accept page in `next`. */
export function inviteTokenFrom(invite: string | null, next: string | null): string | null {
  const direct = (invite ?? "").trim();
  if (/^[A-Za-z0-9_-]{16,512}$/.test(direct)) return direct;
  const m = /^\/orgs\/accept\?(?:.*&)?token=([A-Za-z0-9_-]{16,512})(?:&|$)/.exec((next ?? "").trim());
  return m ? m[1] : null;
}
