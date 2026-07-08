import PartWorkspace from "@/components/workspace/PartWorkspace";

/**
 * Analyze entry to the L2 DECISION frame — same one-drop object, landed on the
 * Manufacturing-engineer lens (Routing & DFM), findings scoped to the
 * recommended route and two-way linked to the 3D part. Session-authed.
 */
export default function AnalyzePage() {
  return <PartWorkspace defaultRole="mfg" />;
}
