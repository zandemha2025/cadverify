/**
 * How a screen names a person: their name, else their email; a deleted account
 * reads "Deleted account".
 *
 * Account deletion keeps the account row as a tombstone whose email becomes
 * `deleted-account-<id>@deleted.invalid` (and clears the name), and the audit
 * rows the person made read `deleted account`. Activity and Members show people
 * through `personLabel`, so neither prints the tombstone address. The backend's
 * twin is `backend/src/services/person_label.py` (the share's "made by", the
 * sign-off stamp and the pilot report's "By" arrive already named by it).
 */
export const DELETED_ACCOUNT = "Deleted account";

const TOMBSTONE = /^deleted-account-\d+@deleted\.invalid$/i;

/** True for a deleted account's tombstone address or redacted audit actor. */
export function isDeletedAccount(email: string | null | undefined): boolean {
  if (typeof email !== "string") return false;
  const value = email.trim();
  return TOMBSTONE.test(value) || value.toLowerCase() === "deleted account";
}

/** The person's name, else their email; "Deleted account" for a deleted one. */
export function personLabel(email: string | null | undefined, name?: string | null): string | null {
  if (isDeletedAccount(email)) return DELETED_ACCOUNT;
  return (name ?? "").trim() || email || null;
}
