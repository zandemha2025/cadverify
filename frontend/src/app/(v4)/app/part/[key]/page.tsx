import { PartPage } from "@/components/v4/part/part-page";

export default async function Page({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return <PartPage partKey={decodeURIComponent(key)} />;
}
