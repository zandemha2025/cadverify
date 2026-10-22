import { ReportScreen } from "@/components/v4/validation/report-screen";

export default async function Page({ searchParams }: { searchParams: Promise<{ run?: string | string[] }> }) {
  const { run } = await searchParams;
  const id = Array.isArray(run) ? run[0] : run;
  return <ReportScreen run={id && /^[0-9A-Za-z]{10,64}$/.test(id) ? id : null} />;
}
