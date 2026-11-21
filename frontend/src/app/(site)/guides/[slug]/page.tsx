import { notFound } from "next/navigation";
import { GrowthPage, growthMetadata } from "@/components/site/growth-page";
import { growthResources, resourceAt } from "@/lib/site/growth-content";

type Props = { params: Promise<{ slug: string }> };
export function generateStaticParams() {
  return growthResources.filter(resource => resource.category === "Guide").map(resource => ({ slug: resource.path.split("/").pop()! }));
}
export async function generateMetadata({ params }: Props) {
  const { slug } = await params;
  const resource = resourceAt(`/guides/${slug}`);
  if (!resource) notFound();
  return growthMetadata(resource.path, resource.title, resource.description);
}
export default async function GuidePage({ params }: Props) {
  const { slug } = await params;
  const resource = resourceAt(`/guides/${slug}`);
  if (!resource) notFound();
  return <GrowthPage resource={resource} />;
}
