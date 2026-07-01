/**
 * Dev-tools gate — keeps internal build tooling out of the customer surface.
 *
 * The corpus annotator ("Parts (Label)") and the design-system showcase
 * ("the build proof") are engineering tools, not customer features, so they must
 * NOT appear in a buyer's nav. They are revealed only when this flag is on, and
 * it is OFF by default.
 *
 * Two ways to turn it on:
 *   - build/runtime:  NEXT_PUBLIC_SHOW_DEV_TOOLS=1  (inlined, SSR-consistent)
 *   - this session:   localStorage["cadverify:dev-tools"] = "1"  (no rebuild)
 *
 * `DEV_TOOLS_ENV` is the SSR-safe value (env only — identical on server + first
 * client paint). `devToolsEnabled()` additionally honors the localStorage
 * opt-in and must be read inside an effect to avoid a hydration mismatch.
 */

export const DEV_TOOLS_STORAGE_KEY = "cadverify:dev-tools";

const flag = process.env.NEXT_PUBLIC_SHOW_DEV_TOOLS;

/** SSR-safe: env flag only (default off). Use as the initial render value. */
export const DEV_TOOLS_ENV = flag === "1" || flag === "true";

/** Full check incl. the session-local localStorage opt-in. Effect-only. */
export function devToolsEnabled(): boolean {
  if (DEV_TOOLS_ENV) return true;
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(DEV_TOOLS_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}
