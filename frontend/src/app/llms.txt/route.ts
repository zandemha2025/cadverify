import { SITE_ORIGIN } from "@/lib/site/growth-routes";
import { growthResources } from "@/lib/site/growth-content";

export function GET() {
  const lines = [
    "# ScaleCAD", "",
    "> Manufacturing decision support from CAD, declared machine capabilities and traceable resource assumptions.", "",
    "Estimates are not supplier quotes. Assumptions and missing inputs must remain visible. Engineering sign-off remains with the responsible team.", "",
    "## Product and evaluation", "",
    ...[["Sample part", "/sample"], ["Method", "/method"], ["Pricing and free-check terms", "/pricing"], ["Security", "/security"], ["Resources", "/resources"]].map(([label, path]) => `- [${label}](${SITE_ORIGIN}${path})`), "",
    "## Guides and tools", "",
    ...growthResources.map(resource => `- [${resource.title}](${SITE_ORIGIN}${resource.path}): ${resource.description}`),
    `- [Make vs buy calculator](${SITE_ORIGIN}/tools/make-vs-buy-calculator): Browser-only fixed and variable cost comparison.`, "",
  ];
  return new Response(lines.join("\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
