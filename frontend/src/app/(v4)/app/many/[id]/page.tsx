import { RunPage } from "@/components/v4/many/run-page";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RunPage batchId={id} />;
}
