import { publicReplayAllowed } from "./analytics-privacy.ts";

export const RB2B_SCRIPT = `!function(key) {if (window.reb2b) return;window.reb2b = {loaded: true};var s = document.createElement("script");s.async = true;s.src = "https://ddwl4m2hdecbv.cloudfront.net/b/" + key + "/" + key + ".js.gz";document.getElementsByTagName("script")[0].parentNode.insertBefore(s, document.getElementsByTagName("script")[0]);}("E63P0HY01JOW");`;

export function rb2bAllowed(hostname: string, path: string, search: string, hash: string, consent: boolean): boolean {
  const params = new URLSearchParams(search);
  const verification = path === "/" && !hash && params.size === 2
    && params.get("verifyge") === "true" && /^[a-f0-9]{32}$/i.test(params.get("ec_b2b") || "");
  return consent && hostname === "scalecad.ai" && (publicReplayAllowed(path, search, hash) || verification);
}
