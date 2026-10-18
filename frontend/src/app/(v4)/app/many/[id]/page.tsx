import { BatchRun } from "@/components/v4/many/batch-run";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <BatchRun batchId={id} />;
}
