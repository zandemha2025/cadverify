import type { MetadataRoute } from "next";
import { GROWTH_ROUTES, SITE_ORIGIN } from "@/lib/site/growth-routes";
import { growthResources } from "@/lib/site/growth-content";

const SITE = SITE_ORIGIN;

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
  return [
    ...PUBLIC_ROUTES.map((route) => ({ url: `${SITE}${route}` })),
    ...GROWTH_ROUTES.map((route) => ({
      url: `${SITE}${route}`,
      // Use known editorial dates, not the time the sitemap was fetched.
      lastModified: growthResources.find(resource => resource.path === route)?.updated,
    })),
  ];
}
