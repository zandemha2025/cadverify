/** The page an invite was sent for (a catalog run), when it is a page in the app; never another site. */
export function inviteNext(raw: string | null | undefined): string | null {
  const p = (raw ?? "").trim();
  return /^\/app\/[A-Za-z0-9/_-]{1,200}$/.test(p) && !p.includes("//") ? p : null;
}
