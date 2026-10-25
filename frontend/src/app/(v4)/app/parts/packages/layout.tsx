import { Suspense } from "react";
import { PackagesScreen } from "@/components/v4/records/packages-screen";

/** RFQ packages: the builder, the list, and one package in the sheet (board P5). The screen lives in the layout so the record selection survives opening a package. */
export default function PackagesLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Suspense fallback={null}>
        <PackagesScreen />
      </Suspense>
      {children}
    </>
  );
}
