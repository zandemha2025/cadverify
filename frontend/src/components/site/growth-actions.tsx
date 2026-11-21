"use client";

import Link from "next/link";
import { track } from "@/lib/analytics";
import { SiteCta, useSiteSession } from "./site-shell";

export function GrowthLink({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) {
  return <Link href={href} className={className} onClick={() => track("resource_link_clicked", { surface: "site", $pathname: location.pathname, $current_url: new URL(href, location.origin).href })}>{children}</Link>;
}

export function GrowthActions() {
  const { freeChecks, user } = useSiteSession();
  return <div>
    <div className="cv-actions">
      <span onClick={() => track(user ? "resource_app_clicked" : "resource_signup_clicked", { surface: "site", $pathname: location.pathname })}><SiteCta /></span>
      <GrowthLink href="/sample" className="cv-text-link">Explore the sample →</GrowthLink>
    </div>
    <p className="growth-terms">{freeChecks.work} free checks with a work email; {freeChecks.personal} with a personal email. No credit card. <GrowthLink href="/pricing">See plan terms.</GrowthLink></p>
  </div>;
}
