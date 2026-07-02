import PartWorkspace from "@/components/workspace/PartWorkspace";

/**
 * Cost / make-vs-buy entry to the L2 DECISION frame. Drop a CAD file → the
 * should-cost decision (make-by, $/unit, lead, the make-vs-buy crossover
 * scrubber) with the glass-box drivers, routing/DFM and the resident Inspector
 * one click away. Lands on the Design lens (answer-first). Session-authed.
 */
export default function CostPage() {
  return <PartWorkspace defaultRole="design" />;
}
