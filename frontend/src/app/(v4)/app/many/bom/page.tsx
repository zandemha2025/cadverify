import { BomScreen } from "@/components/v4/many/bom-screen";

export default async function Page({ searchParams }: { searchParams: Promise<{ profile?: string | string[] }> }) {
  const { profile } = await searchParams;
  return <BomScreen profileId={typeof profile === "string" && profile ? profile : null} />;
}
