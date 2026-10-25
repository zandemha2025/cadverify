import { Suspense } from "react";
import { CompareScreen } from "@/components/v4/records/compare-screen";

/** Compare two records (board P3). `?a=` and `?b=` pick the records. */
export default function Page() {
  return (
    <Suspense fallback={null}>
      <CompareScreen />
    </Suspense>
  );
}
