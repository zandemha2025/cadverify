import type { Metadata } from "next";
import { PreciseHome } from "@/components/site/precise-home";

export const metadata: Metadata = {
  title: "ScaleCAD — Can you make it?",
  description: "Upload a 3D model of a part. ScaleCAD tells you whether your machines can make it, which materials will hold up, how long it takes and what it costs. Every number shows where it came from.",
  alternates: { canonical: "/" },
};
export default function HomePage() { return <PreciseHome />; }
