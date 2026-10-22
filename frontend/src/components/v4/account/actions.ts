"use server";
/**
 * Create or rotate an API key from the v4 API page and hand its one-time
 * secret to this page only.
 *
 * The backend returns a new key's secret once, in the create or rotate
 * response body. This action calls it server-side with the session cookie and
 * returns the secret in its own result, straight to the page that asked.
 * Nothing stores it and no cookie carries it. (It used to be passed on in a
 * 60-second, script-readable `cv_mint_once` cookie; whenever the browser or a
 * proxy dropped that cookie, a Secure cookie over plain http for one, the page
 * said "the secret didn't arrive" and left a live key nobody had seen.)
 *
 * A key the person never received can't stay live: if the backend made a key
 * but no secret came back, it is revoked at once and the result says so
 * (./key-mint.ts).
 */
import { cookies } from "next/headers";
import { backendUrl } from "@/lib/api-base";
import { mintWith, type MintOp, type MintResult } from "./key-mint";

export async function mintKey(op: MintOp): Promise<MintResult> {
  const jar = await cookies();
  return mintWith({ url: backendUrl, fetch }, jar.get("dash_session")?.value, op);
}
