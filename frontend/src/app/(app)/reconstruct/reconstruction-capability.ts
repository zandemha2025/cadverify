import type { ReconstructionCapability } from "@/lib/api";

export interface ReconstructionSubmissionGate {
  allowed: boolean;
  reason: string | null;
}

export function reconstructionSubmissionGate(
  capability: ReconstructionCapability | null,
  egressAcknowledged: boolean,
): ReconstructionSubmissionGate {
  if (!capability) {
    return { allowed: false, reason: "Image-to-3D availability is still loading." };
  }
  if (!capability.available) {
    return { allowed: false, reason: "Image-to-3D is not enabled for this workspace." };
  }
  if (!capability.can_submit) {
    return { allowed: false, reason: "An analyst role or higher is required to submit images." };
  }
  if (capability.requires_egress_acknowledgement && !egressAcknowledged) {
    return {
      allowed: false,
      reason: "Acknowledge third-party data processing before submitting.",
    };
  }
  return { allowed: true, reason: null };
}
