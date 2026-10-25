// Keep in sync with backend/src/auth/email_tier.py (verified by the parity test).
export const PERSONAL_DOMAINS = ["gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com", "pm.me", "gmx.com", "gmx.de", "mail.com", "yandex.com", "zoho.com", "fastmail.com", "fastmail.fm", "hey.com", "tuta.io", "tutanota.com"];
export function emailTier(email: string): "work" | "personal" | null {
  const match = /^[^@\s]+@([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})$/i.exec(email.trim());
  return match ? PERSONAL_DOMAINS.includes(match[1].toLowerCase()) ? "personal" : "work" : null;
}
