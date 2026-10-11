import type { MetadataRoute } from "next";

const SITE = process.env.NEXT_PUBLIC_SITE_URL || "https://scalecad.ai";

const PUBLIC_ROUTES = [
  "",
  "/sample",
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
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return PUBLIC_ROUTES.map((route) => ({
    url: `${SITE}${route}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: route === "" ? 1 : 0.7,
  }));
}
