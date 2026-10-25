import { Suspense } from "react";
import { Workbench } from "@/components/v4/workbench/workbench";

/** The part's cost breakdown, under the part (tabs by ?tab=). */
export default async function Page({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return (
    <Suspense fallback={null}>
      <Workbench part={decodeURIComponent(key)} />
    </Suspense>
  );
}
