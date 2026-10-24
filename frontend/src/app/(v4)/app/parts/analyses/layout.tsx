import { AnalysesScreen } from "@/components/v4/records/analyses-screen";

/** Analyses list and the selected analysis (board P4). The screen lives in the layout so the list keeps its place while the selection changes. */
export default function AnalysesLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AnalysesScreen />
      {children}
    </>
  );
}
