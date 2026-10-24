/**
 * Which free-check tier an email address falls in, for the live hint on the
 * sign-in and sign-up forms. Mirrors backend/src/auth/email_tiers.py (the
 * server decides; this only predicts what it will say). `null` until the text
 * looks like an address.
 */
export const PERSONAL_EMAIL_DOMAINS: ReadonlySet<string> = new Set([
  "gmail.com", "googlemail.com",
  "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "msn.com", "passport.com",
  "yahoo.com", "yahoo.co.uk", "yahoo.ca", "yahoo.com.au", "yahoo.co.in", "yahoo.fr", "yahoo.de", "ymail.com", "rocketmail.com",
  "icloud.com", "me.com", "mac.com",
  "aol.com", "aim.com",
  "proton.me", "protonmail.com", "pm.me",
  "tuta.io", "tutanota.com", "tutamail.com",
  "fastmail.com", "fastmail.fm",
  "gmx.com", "gmx.net", "gmx.de", "web.de",
  "mail.com", "email.com", "zoho.com", "zohomail.com",
  "yandex.com", "yandex.ru", "mail.ru",
  "qq.com", "163.com", "126.com", "sina.com", "foxmail.com",
  "naver.com", "hanmail.net", "daum.net",
  "comcast.net", "verizon.net", "att.net", "sbcglobal.net", "bellsouth.net", "cox.net", "charter.net", "earthlink.net",
  "hey.com", "duck.com", "mailfence.com", "hushmail.com", "inbox.com", "rediffmail.com",
  "btinternet.com", "orange.fr", "free.fr", "laposte.net", "libero.it", "t-online.de",
]);

export type EmailTier = "work" | "personal";

export function emailTier(email: string): EmailTier | null {
  const text = email.trim();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(text)) return null;
  const domain = text.slice(text.lastIndexOf("@") + 1).toLowerCase().replace(/\.+$/, "");
  return PERSONAL_EMAIL_DOMAINS.has(domain) ? "personal" : "work";
}

/** The chip and line shown under an email field. */
export function tierHint(email: string, free: { work: number; personal: number }): { tone: "ok" | "warn" | "unk"; chip: string; text: string } {
  const tier = emailTier(email);
  if (tier === "work") return { tone: "ok", chip: `${free.work} free checks`, text: "Work email" };
  if (tier === "personal") return { tone: "warn", chip: `${free.personal} free checks`, text: `Personal email · work email gets ${free.work}` };
  return { tone: "unk", chip: "Free checks", text: `Work email ${free.work} · personal ${free.personal}` };
}
