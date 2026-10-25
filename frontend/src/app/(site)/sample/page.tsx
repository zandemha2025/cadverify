import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { SiteShell } from "@/components/site/site-shell";
import { SampleExplorer } from "@/components/site/sample-explorer";
export const metadata: Metadata = { title: "Explore a sample part — ScaleCad", description: "Inspect the process recommendation, design findings and source-backed estimate for a recorded ScaleCad sample.", alternates: { canonical: "/sample" } };
export default async function SamplePage({ searchParams }: { searchParams: Promise<{ view?: string }> }) {
  const { view } = await searchParams;
  const initialView = view === "design" || view === "resources" ? view : "process";
  return <SiteShell><section className="cv-wrap cv-sample-page"><Link href="/" className="cv-text-link"><ArrowLeft size={16} aria-hidden="true" /> Back to overview</Link><div className="cv-section-intro"><h1>A part you can<br />get to know.</h1><p>Explore a recorded analysis, from the geometry to the assumptions. No upload, account or live calculation needed.</p></div><SampleExplorer initialView={initialView} standalone /></section></SiteShell>;
}
