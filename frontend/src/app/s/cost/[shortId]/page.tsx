import type { Metadata } from "next";
import { SharedCost } from "@/components/v4/home/shared-cost";
import { SharedOff } from "@/components/v4/home/shared-frame";
import type { SupplierPart } from "@/components/v4/home/supplier-view";
import { readPublicShare } from "@/components/v4/datacontrol/api";
import { day } from "@/components/v4/datacontrol/words";

/**
 * A part's share link, as its supplier sees it (backend GET /s/cost/{id},
 * src/services/supplier_links.py): the part, specs, quantity, the buyer's note,
 * the CAD when included, and the buyer's cost estimate only when they turned it
 * on. Not indexed; no sign-up call to action (buyer-12, buyer-14).
 */
export async function generateMetadata({ params }: { params: Promise<{ shortId: string }> }): Promise<Metadata> {
  const { shortId } = await params;
  const res = await readPublicShare<SupplierPart>(`/s/cost/${shortId}`);
  const title = res.ok ? `${res.data.label || res.data.name || res.data.filename} - Request for quote` : "Shared part";
  return { title, robots: { index: false, follow: false } };
}

export default async function SharedPartPage({ params }: { params: Promise<{ shortId: string }> }) {
  const { shortId } = await params;
  // 410 when the link ended or was switched off (no record data), 404 when unknown.
  const res = await readPublicShare<SupplierPart>(`/s/cost/${shortId}`);
  if (res.ok) return <SharedCost data={res.data} />;
  return <SharedOff reason={res.reason} endedOn={day(res.endedAt)} />;
}
