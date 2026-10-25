/**
 * Photo to 3D (board F4) words and rules, kept pure so they can be tested:
 * what the server's capability means for the screen, the four steps, photo
 * validation, the Reconstruct button, and the job's progress line. Nothing is
 * faked: with the capability off, nothing can be uploaded.
 */
import type { ReconstructionCapability } from "../../../lib/api";

export const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"];
export const PHOTO_ACCEPT = ".jpg,.jpeg,.png,.webp";
export const MAX_PHOTOS = 4;
export const MAX_PHOTO_BYTES = 20 * 1024 * 1024;

export type Mode = "loading" | "error" | "off" | "egress" | "local";

export function modeOf(cap: ReconstructionCapability | null, failed: boolean): Mode {
  if (failed) return "error";
  if (!cap) return "loading";
  if (!cap.available) return "off";
  return cap.requires_egress_acknowledgement || cap.customer_data_egress ? "egress" : "local";
}

export function metaState(mode: Mode): string {
  if (mode === "off") return "Off on this server";
  if (mode === "egress") return "Third-party provider";
  if (mode === "local") return "Runs in this deployment";
  return mode === "error" ? "Availability unknown" : "Checking availability";
}

export function sheetMeta(mode: Mode): string {
  if (mode === "off") return "Off on this server · nothing can be uploaded";
  if (mode === "egress") return "Third-party provider · approve, then add photos";
  if (mode === "local") return "In this deployment";
  return mode === "error" ? "Availability check didn’t finish" : "Checking availability";
}

export type Phase = "upload" | "proc" | "done";

/** Which of the four steps is current (0 while the tool is off). */
export function stepNow(mode: Mode, phase: Phase, photos: number): number {
  if (mode !== "egress" && mode !== "local") return 0;
  if (phase === "done") return 4;
  if (phase === "proc") return 3;
  return photos ? 2 : 1;
}

export function steps(mode: Mode): { t: string; d: string }[] {
  return [
    { t: "Approve", d: mode === "egress" ? "Consent to the third-party transfer" : mode === "local" ? "Approved for this deployment" : "Admin enables a backend" },
    { t: "Add photos", d: "1 to 4, several angles" },
    { t: "Reconstruct", d: "Usually about a minute" },
    { t: "Review", d: "Mesh, confidence, then DFM" },
  ];
}

export function stepNote(mode: Mode, step: number): string {
  if (mode === "off" || mode === "error" || mode === "loading") return "Available after an admin approves a backend";
  return `Step ${Math.max(1, step)} of 4`;
}

/** The first problem with adding these photos, or null. */
export function photoProblem(current: number, incoming: { name: string; type: string; size: number }[]): string | null {
  if (current + incoming.length > MAX_PHOTOS)
    return `Up to ${MAX_PHOTOS} photos. You have ${current}; that would make ${current + incoming.length}.`;
  for (const f of incoming) {
    if (!PHOTO_TYPES.includes(f.type)) return `“${f.name}” isn’t a JPEG, PNG or WebP image.`;
    if (f.size > MAX_PHOTO_BYTES) return `“${f.name}” is over 20 MB.`;
  }
  return null;
}

export function canAdd(mode: Mode, consent: boolean, photos: number): boolean {
  return (mode === "local" || (mode === "egress" && consent)) && photos < MAX_PHOTOS;
}

export function dropTitle(mode: Mode, consent: boolean, photos: number): string {
  if (mode !== "egress" && mode !== "local") return "Uploads are off";
  if (mode === "egress" && !consent) return "Approve the transfer first";
  if (photos >= MAX_PHOTOS) return `${MAX_PHOTOS} photos added`;
  return "Drop photos or click to add";
}

export function goLabel(photos: number): string {
  return "Reconstruct" + (photos ? ` (${photos} image${photos === 1 ? "" : "s"})` : "");
}

export function goHint(mode: Mode, consent: boolean, photos: number): string {
  if (mode !== "egress" && mode !== "local") return "Off on this server";
  if (mode === "egress" && !consent) return "Approve the transfer";
  if (!photos) return "Add at least 1 photo";
  return "";
}

export function statusLabel(status: string): string {
  if (status === "queued") return "Preparing images…";
  if (status === "running") return "Building 3D model…";
  if (status === "partial") return "Finishing with limited output…";
  if (status === "done") return "Loading the result…";
  return "Building 3D model…";
}

/** Estimated progress, capped below done: the server reports no percentage, only time is real. */
export function progressFraction(elapsed: number, estimated: number): number {
  return Math.min(0.95, Math.max(0.05, elapsed / Math.max(1, estimated)));
}

export function levelWord(level: "high" | "medium" | "low"): string {
  return level === "high" ? "High" : level === "medium" ? "Medium" : "Low";
}
