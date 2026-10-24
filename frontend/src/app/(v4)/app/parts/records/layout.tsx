import { RecordsScreen } from "@/components/v4/records/records-screen";

/** Records list and the selected record (board P2). The screen lives in the layout so the list keeps its place while the selection changes. */
export default function RecordsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <RecordsScreen />
      {children}
    </>
  );
}
