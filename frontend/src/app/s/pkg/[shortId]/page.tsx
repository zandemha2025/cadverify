import type { Metadata } from "next";
import { SharedPackage } from "@/components/v4/home/shared-package";
import { SharedOff } from "@/components/v4/home/shared-frame";
import type { SupplierPackage } from "@/components/v4/home/supplier-view";
import { readPublicShare } from "@/components/v4/datacontrol/public-share";
import { day } from "@/components/v4/datacontrol/words";

/**
 * An RFQ package's share link, as its supplier sees it (backend GET /s/pkg/{id},
 * src/services/supplier_links.py): the request for quote part by part, each
 * part's CAD and the whole ZIP. Not indexed; no sign-up call to action.
 */
export async function generateMetadata({ params }: { params: Promise<{ shortId: string }> }): Promise<Metadata> {
  const { shortId } = await params;
  const res = await readPublicShare<SupplierPackage>(`/s/pkg/${shortId}`);
  return { title: res.ok ? `${res.data.title} - Request for quote` : "Shared package", robots: { index: false, follow: false } };
}

export default async function SharedPackagePage({ params }: { params: Promise<{ shortId: string }> }) {
  const { shortId } = await params;
  const res = await readPublicShare<SupplierPackage>(`/s/pkg/${shortId}`);
  if (res.ok) return <SharedPackage data={res.data} />;
  return <SharedOff reason={res.reason} endedOn={day(res.endedAt)} />;
}
