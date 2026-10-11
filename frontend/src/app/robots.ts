import type { MetadataRoute } from "next";

const SITE = process.env.NEXT_PUBLIC_SITE_URL || "https://scalecad.ai";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: [
          "/",
          "/method",
          "/platform",
          "/teams",
          "/teams/cost-engineering",
          "/teams/design-engineering",
          "/teams/in-house-manufacturing",
          "/teams/shop-owners",
          "/teams/sourcing",
          "/security",
          "/developers",
          "/company",
          "/pricing",
          "/contact",
          "/pilot",
          "/privacy",
          "/terms",
          "/dpa",
          "/status",
          "/api-reference",
          "/pilot-report",
        ],
        disallow: [
          "/analyze",
          "/batch",
          "/cost",
          "/cost-decisions",
          "/history",
          "/label",
          "/reconstruct",
          "/settings",
          "/verify",
          "/login",
          "/signup",
          "/magic",
          "/orgs",
        ],
      },
    ],
    sitemap: `${SITE}/sitemap.xml`,
  };
}
