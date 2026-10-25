import { Suspense } from "react";
import type { Metadata } from "next";
import { UI_V4 } from "@/lib/ui-v4-flag";
import { V4TwoStep } from "@/components/v4/moments/two-step";
import { LegacyTwoStep } from "./legacy-two-step";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Two-step sign-in - ScaleCAD",
  robots: { index: false, follow: false },
};

export default function TwoStepPage() {
  return <Suspense fallback={null}>{UI_V4 ? <V4TwoStep /> : <LegacyTwoStep />}</Suspense>;
}
