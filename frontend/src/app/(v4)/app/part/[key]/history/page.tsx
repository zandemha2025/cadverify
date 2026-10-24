import { HistoryPage } from "@/components/v4/part/history-page";

export default async function Page({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return <HistoryPage partKey={decodeURIComponent(key)} />;
}
