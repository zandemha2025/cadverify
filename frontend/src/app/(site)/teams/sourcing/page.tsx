import type { Metadata } from "next";
import { SourcingView } from "./sourcing-view";

/**
 * /teams/sourcing — "For Sourcing" (Teams / Sourcing & procurement).
 *
 * Design source: `handoff_cadverify_2026-07-04/site/For Sourcing.dc.html`
 * (ROUTE-PLAN #12). A cinematic persona journey nested under /teams/*; the
 * Teams nav link stays lit for the subtree (SiteNav uses startsWith).
 *
 * Server component so it can carry its own metadata; the interactive body
 * (WebGL stage + scroll-measured caption reveals) is the client SourcingView.
 */

export const metadata: Metadata = {
  title: "For Sourcing — ProofShape",
  description:
    "The sourcing-native verdict: for every part, the computed choice — make in-house on the floor you own, make outside, or acquire the capability — with the resource math underneath.",
};

export default function SourcingPage() {
  return <SourcingView />;
}
