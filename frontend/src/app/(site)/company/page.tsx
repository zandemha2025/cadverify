import type { Metadata } from "next";

import CompanyView from "./company-view";

/**
 * /company — Company page (dark-theater document register).
 *
 * Thin Server Component: owns the page metadata and renders the client
 * `CompanyView`. The view must be a Client Component because it consumes the
 * `@/components/site` foundation barrel, which re-exports the client-only
 * scroll-act hooks (see company-view.tsx). Recreated from
 * handoff_cadverify_2026-07-04/site/Company.dc.html.
 */

export const metadata: Metadata = {
  title: "Company — CadVerify",
  description:
    "Manufacturing runs on numbers nobody can check. We built the glass box: a cost-truth engine where every number carries its provenance, every total reconciles on screen, and accuracy is measured on your parts — never asserted.",
};

export default function CompanyPage() {
  return <CompanyView />;
}
