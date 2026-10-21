import { CatalogSummary } from "@/components/v4/many/catalog-summary";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CatalogSummary batchId={id} />;
}
