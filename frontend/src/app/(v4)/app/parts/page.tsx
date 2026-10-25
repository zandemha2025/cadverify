import { Suspense } from "react";
import { PartsScreen } from "@/components/v4/home/parts-screen";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <PartsScreen />
    </Suspense>
  );
}
