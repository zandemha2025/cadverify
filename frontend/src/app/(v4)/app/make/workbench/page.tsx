import { Suspense } from "react";
import { Workbench } from "@/components/v4/workbench/workbench";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <Workbench />
    </Suspense>
  );
}
