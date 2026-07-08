import { LandingEntry } from "@/components/landing/LandingEntry";

/**
 * The app home (rail brand + Workbench both land here).
 *
 * Flag-on (D5 FE-3): the three-door landing router — first-run door chooser, then
 * the persona's door hero (part door live; catalog/portfolio honest coming-states).
 *
 * Flag-off: today's landing, untouched and byte-identical — drop a CAD file → the
 * should-cost decision on the Design lens (answer-first). The flag branch and the
 * lazy import both live in `LandingEntry` (a client boundary), so the three-door
 * surface is code-split out of the flag-off `/cost` bundle entirely.
 */
export default function CostPage() {
  return <LandingEntry />;
}
