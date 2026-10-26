import type { Metadata } from "next";
import "./site.css";
import "./precise.css";
import { siteFonts } from "@/lib/site/fonts";
import { SiteSessionBoundary } from "@/components/site/site-session";

export const metadata: Metadata = {
  title: "ScaleCAD — Can you make it?",
  description: "Make manufacturing decisions with traceable evidence. Explore a sample, review the findings, and bring your own part.",
};

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return <SiteSessionBoundary><div className={`cv-site ${siteFonts}`}>{children}</div></SiteSessionBoundary>;
}
