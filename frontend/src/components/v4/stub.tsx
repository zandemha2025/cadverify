"use client";

/** Temporary screen used until a route's real screen lands. */
import { Content, Empty, PageHead, World } from "./ui";
import { TABS, type NavSection } from "./routes";

export function Stub({ title, section, board }: { title: string; section: NavSection; board: string }) {
  return (
    <World label={title}>
      <PageHead title={title} meta={[`Design board ${board}`]} tabs={section === "home" ? undefined : TABS[section]} tabsLabel={title} wide />
      <Content full>
        <div className="panel">
          <Empty title="Not built yet">This screen is being rebuilt from design board {board}.</Empty>
        </div>
      </Content>
    </World>
  );
}
