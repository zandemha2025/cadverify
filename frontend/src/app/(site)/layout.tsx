import type { Metadata } from "next";
import "./site.css";

export const metadata: Metadata = {
  title: "CadVerify — Know what you can make",
  description: "Make manufacturing decisions with traceable evidence. Explore a sample, review the findings, and bring your own part.",
};

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return <div className="cv-site">{children}</div>;
}
