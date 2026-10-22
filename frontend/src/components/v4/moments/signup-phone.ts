/**
 * The phone number typed at sign-up, carried to the phone check.
 *
 * When free checks need a verified phone, creating the account sends the code
 * to the number typed there at once, and the phone check opens on "Enter code"
 * instead of asking for the number again. This tab's sessionStorage carries
 * what happened (the number, when the code went, or why it didn't) for a short
 * while; the server keeps the number itself (GET /account/phone), so a later
 * visit still finds it filled in.
 */

export type SignupPhone = {
  phone: string;
  /** When the code was sent (ms), or null when it wasn't. */
  sentAt: number | null;
  /** Why the code wasn't sent, in the server's words. */
  error: string | null;
};

export type GateStart = { step: "phone" | "code"; phone: string; error: string | null; resendIn: number };

type KV = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const KEY = "scalecad.signup-phone";
/** A code from sign-up is still worth typing for this long (Twilio Verify codes last 10 minutes). */
export const CODE_FRESH_MS = 10 * 60 * 1000;
export const RESEND_S = 30;

export function rememberSignupPhone(store: KV | null, value: SignupPhone): void {
  try {
    store?.setItem(KEY, JSON.stringify(value));
  } catch {
    // Private modes: the phone check simply asks for the number again.
  }
}

export function readSignupPhone(store: KV | null, now = Date.now()): SignupPhone | null {
  try {
    const raw = store?.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<SignupPhone>;
    if (typeof v.phone !== "string" || !v.phone.trim()) return null;
    const sentAt = typeof v.sentAt === "number" && now - v.sentAt < CODE_FRESH_MS && v.sentAt <= now ? v.sentAt : null;
    return { phone: v.phone, sentAt, error: typeof v.error === "string" ? v.error : null };
  } catch {
    return null;
  }
}

export function clearSignupPhone(store: KV | null): void {
  try {
    store?.removeItem(KEY);
  } catch {
    // Nothing to clear.
  }
}

/** Where the phone check opens: on the code when sign-up sent one, else on the number (filled in when known). */
export function gateStart(fromSignup: SignupPhone | null, onFile: string | null, now = Date.now()): GateStart {
  if (fromSignup?.sentAt != null) {
    const waited = Math.floor((now - fromSignup.sentAt) / 1000);
    return { step: "code", phone: fromSignup.phone, error: null, resendIn: Math.max(0, RESEND_S - waited) };
  }
  if (fromSignup) return { step: "phone", phone: fromSignup.phone, error: fromSignup.error, resendIn: 0 };
  return { step: "phone", phone: onFile ?? "", error: null, resendIn: 0 };
}

export function sessionStore(): KV | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}
